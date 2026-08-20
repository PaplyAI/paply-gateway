// Paply 保留 Octopus 的布局组件，但使用 PaplyAI 自有品牌资产。
export default function Logo({ size = 48 }: { size?: number | string }) {
    return (
        <img
            src={`${import.meta.env.BASE_URL}paplyai-logo.png`}
            alt="PaplyAI"
            width={size}
            height={size}
            className="rounded-2xl object-cover"
        />
    );
}
