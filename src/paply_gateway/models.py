from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ModelMetadata(StrictModel):
    name: str | None = None
    description: str | None = None
    note: str | None = None


class ChatModel(StrictModel):
    id: str = Field(min_length=1)
    name: str | None = None
    input: list[Literal["text", "image", "audio", "video"]] = Field(min_length=1)
    reasoning: bool | None = None
    thinking_levels: list[str] | None = Field(default=None, alias="thinkingLevels")
    context_window: int | None = Field(default=None, alias="contextWindow", gt=0)
    max_output_tokens: int | None = Field(default=None, alias="maxOutputTokens", gt=0)

    @model_validator(mode="after")
    def require_text_input(self) -> "ChatModel":
        if "text" not in self.input:
            raise ValueError("every chat model must accept text input")
        return self


class ChatProviderTemplate(StrictModel):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(min_length=1)
    api: Literal["openai-responses", "openai-completions"]
    models: list[ChatModel] = Field(min_length=1)


class ChatConfig(StrictModel):
    providers: list[ChatProviderTemplate]

    @model_validator(mode="after")
    def unique_provider_ids(self) -> "ChatConfig":
        ids = [provider.id for provider in self.providers]
        if len(ids) != len(set(ids)):
            raise ValueError("chat provider ids must be unique")
        return self


class MediaProviderTemplate(StrictModel):
    provider: str = Field(min_length=1)
    api_type: Literal[
        "openai-responses",
        "openai-images",
        "openai-chat-image",
        "google-generative-ai-image",
        "dashscope-native",
    ] = Field(alias="apiType")
    model_id: str = Field(alias="modelId", min_length=1)


class ModelsTemplate(StrictModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    meta: ModelMetadata | None = None
    chat: ChatConfig
    vision: MediaProviderTemplate | None
    image_gen: MediaProviderTemplate | None = Field(alias="imageGen")

    def materialize(self, *, base_url: str, api_key: str) -> dict[str, object]:
        document = self.model_dump(by_alias=True, exclude_none=True)
        chat = document["chat"]
        assert isinstance(chat, dict)
        providers = chat["providers"]
        assert isinstance(providers, list)
        for provider in providers:
            assert isinstance(provider, dict)
            provider["baseUrl"] = base_url
            provider["apiKey"] = api_key
        for key in ("vision", "imageGen"):
            media = document.get(key)
            if isinstance(media, dict):
                media["baseUrl"] = base_url
                media["apiKey"] = api_key
            elif key not in document:
                document[key] = None
        return document


def load_models_template(path: Path) -> ModelsTemplate:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"models configuration does not exist: {path}") from error
    except OSError as error:
        raise RuntimeError(f"models configuration cannot be read: {path}") from error
    except yaml.YAMLError as error:
        raise RuntimeError(f"models configuration is invalid YAML: {path}") from error
    try:
        return ModelsTemplate.model_validate(payload)
    except ValueError as error:
        raise RuntimeError(f"models configuration violates the desktop contract: {path}") from error

