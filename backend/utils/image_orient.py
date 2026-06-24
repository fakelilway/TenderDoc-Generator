"""按 EXIF 朝向把图片摆正,再交给 python-docx 插入。

相机/手机拍的扫描件常带 EXIF Orientation 标签(转90/180/270),浏览器认、但 Word 的
add_picture 不认 → 插进去就侧躺/倒置。这里在插入前用 PIL exif_transpose 把旋转"烤进像素"
并清掉 Orientation 标签,确保 Word 里朝向正确。无标签/失败则原样返回(绝不因此丢图)。
"""

from __future__ import annotations

from io import BytesIO

_ORIENTATION_TAG = 0x0112  # EXIF Orientation


def upright_image_bytes(image_bytes: bytes) -> bytes:
    """返回按 EXIF 摆正后的图片字节;不需要或失败则返回原字节。"""
    if not image_bytes:
        return image_bytes
    try:
        from PIL import Image, ImageOps

        im = Image.open(BytesIO(image_bytes))
        fmt = (im.format or "JPEG").upper()
        orientation = im.getexif().get(_ORIENTATION_TAG, 1)
        if orientation in (1, 0, None):
            return image_bytes  # 正向或无朝向标签,不动

        fixed = ImageOps.exif_transpose(im)  # 应用旋转并清掉 Orientation 标签
        save_fmt = "PNG" if fmt == "PNG" else "JPEG"
        if save_fmt == "JPEG" and fixed.mode in ("RGBA", "P", "LA"):
            fixed = fixed.convert("RGB")
        out = BytesIO()
        fixed.save(out, format=save_fmt, quality=90)
        return out.getvalue()
    except Exception:
        return image_bytes
