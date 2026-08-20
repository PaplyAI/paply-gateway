"""DashScope Qwen-Image edit compatibility for pinned LiteLLM v1.96.0."""

from __future__ import annotations

import base64
from typing import Any

import httpx
from litellm import LlmProviders
from litellm.llms.base_llm.image_edit.transformation import BaseImageEditConfig
from litellm.llms.dashscope.image_generation.transformation import (
    DashScopeImageGenerationConfig,
)
from litellm.types.utils import ImageObject, ImageResponse
from litellm.utils import ProviderConfigManager

IMAGE_PATH = "/services/aigc/multimodal-generation/generation"
_installed = False


def _image_bytes(value: Any) -> tuple[bytes, str]:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value), "image/png"
    file_value = getattr(value, "file", value)
    read = getattr(file_value, "read", None)
    if not callable(read):
        raise ValueError("DashScope image edit input must be an uploaded image")
    position = file_value.tell() if callable(getattr(file_value, "tell", None)) else None
    content = read()
    if position is not None and callable(getattr(file_value, "seek", None)):
        file_value.seek(position)
    if not isinstance(content, bytes):
        raise ValueError("DashScope image edit input could not be read")
    return content, getattr(value, "content_type", None) or "image/png"


class DashScopeImageEditConfig(BaseImageEditConfig):
    def get_supported_openai_params(self, model: str) -> list:
        return ["image", "prompt", "n", "size"]

    def map_openai_params(
        self,
        image_edit_optional_params: dict,
        model: str,
        drop_params: bool,
    ) -> dict:
        return {
            key: value
            for key, value in image_edit_optional_params.items()
            if key in {"n", "size"}
        }

    def validate_environment(
        self,
        headers: dict,
        model: str,
        api_key: str | None = None,
        litellm_params: dict | None = None,
        api_base: str | None = None,
    ) -> dict:
        if not api_key:
            raise ValueError("DashScope image edit API key is missing")
        return {
            **headers,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def get_complete_url(
        self,
        model: str,
        api_base: str | None,
        litellm_params: dict,
    ) -> str:
        if not api_base:
            raise ValueError("DashScope image edit API base is missing")
        normalized = api_base.rstrip("/")
        return normalized if normalized.endswith(IMAGE_PATH) else f"{normalized}{IMAGE_PATH}"

    def transform_image_edit_request(
        self,
        model: str,
        prompt: str | None,
        image: Any,
        image_edit_optional_request_params: dict,
        litellm_params: Any,
        headers: dict,
    ) -> tuple[dict, list]:
        if not prompt or not prompt.strip():
            raise ValueError("DashScope image edit prompt is required")
        images = image if isinstance(image, list) else [image]
        content: list[dict[str, str]] = []
        for item in images:
            raw, content_type = _image_bytes(item)
            encoded = base64.b64encode(raw).decode("ascii")
            content.append({"image": f"data:{content_type};base64,{encoded}"})
        if not content or len(content) > 3:
            raise ValueError("DashScope image edit accepts between one and three images")
        content.append({"text": prompt.strip()})
        parameters: dict[str, Any] = {"prompt_extend": True, "watermark": False}
        count = image_edit_optional_request_params.get("n")
        if count is not None:
            parameters["n"] = count
        size = image_edit_optional_request_params.get("size")
        if isinstance(size, str):
            parameters["size"] = size.replace("x", "*")
        return (
            {
                "model": model,
                "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": parameters,
            },
            [],
        )

    def transform_image_edit_response(
        self,
        model: str,
        raw_response: httpx.Response,
        logging_obj: Any,
    ) -> ImageResponse:
        if raw_response.status_code != 200:
            raise self.get_error_class(
                error_message=raw_response.text,
                status_code=raw_response.status_code,
                headers=raw_response.headers,
            )
        document = raw_response.json()
        if "code" in document and "output" not in document:
            raise self.get_error_class(
                error_message=str(document.get("message", document)),
                status_code=422,
                headers=raw_response.headers,
            )
        images: list[ImageObject] = []
        for choice in document.get("output", {}).get("choices", []):
            for item in choice.get("message", {}).get("content", []):
                if isinstance(item.get("image"), str):
                    images.append(ImageObject(url=item["image"]))
        if not images:
            raise self.get_error_class(
                error_message="DashScope image edit response contained no image",
                status_code=502,
                headers=raw_response.headers,
            )
        return ImageResponse(data=images)

    def use_multipart_form_data(self) -> bool:
        return False


def install_dashscope_image_edit() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    original = ProviderConfigManager.get_provider_image_edit_config

    def get_provider_image_edit_config(model: str, provider: LlmProviders):
        if provider == LlmProviders.DASHSCOPE:
            return DashScopeImageEditConfig()
        return original(model, provider)

    ProviderConfigManager.get_provider_image_edit_config = staticmethod(
        get_provider_image_edit_config
    )

    def map_image_generation_params(
        self: DashScopeImageGenerationConfig,
        non_default_params: dict,
        optional_params: dict,
        model: str,
        drop_params: bool,
    ) -> dict:
        mapped: dict[str, Any] = {}
        count = non_default_params.get("n")
        if count is not None:
            mapped["n"] = count
        size = non_default_params.get("size")
        if isinstance(size, str):
            mapped["size"] = size.replace("x", "*")
        return mapped

    original_transform = DashScopeImageGenerationConfig.transform_image_generation_request

    def transform_image_generation_request(
        self: DashScopeImageGenerationConfig,
        model: str,
        prompt: str,
        optional_params: dict,
        litellm_params: dict,
        headers: dict,
    ) -> dict:
        document = original_transform(
            self,
            model,
            prompt,
            optional_params,
            litellm_params,
            headers,
        )
        document["parameters"] = {
            "prompt_extend": True,
            "watermark": False,
            **document.get("parameters", {}),
        }
        return document

    DashScopeImageGenerationConfig.map_openai_params = map_image_generation_params
    DashScopeImageGenerationConfig.transform_image_generation_request = (
        transform_image_generation_request
    )
