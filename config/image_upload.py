"""Shared helpers to keep image uploads small on shared hosting."""

from __future__ import annotations

from io import BytesIO

from django.core.files.uploadedfile import InMemoryUploadedFile
from rest_framework.exceptions import ValidationError as DRFValidationError


def safe_image_filename(uploaded, *, default_stem="image", force_ext=None) -> str:
    import re

    raw = (getattr(uploaded, "name", "") or default_stem).replace("\\", "/").split("/")[-1]
    stem, dot, ext = raw.rpartition(".")
    if not dot:
        stem, ext = raw, "jpg"
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_") or default_stem
    ext = (force_ext or ext or "jpg").lower().lstrip(".")
    if ext not in {"jpg", "jpeg", "png", "webp", "gif", "bmp"}:
        ext = "jpg"
    if ext == "jpeg":
        ext = "jpg"
    return f"{stem[:60]}.{ext}"


def prepare_image_upload(
    uploaded,
    *,
    field_name: str = "image",
    default_stem: str = "image",
    max_edge: int = 1600,
    reencode_over_bytes: int = 700_000,
    jpeg_quality: int = 82,
) -> InMemoryUploadedFile:
    """
    Copy upload into memory and optionally downscale large images.
    Avoids closed TemporaryUploadedFile issues after PIL on Passenger.
    """
    try:
        uploaded.seek(0)
    except Exception:
        pass
    data = uploaded.read()
    try:
        uploaded.seek(0)
    except Exception:
        pass

    if not data:
        raise DRFValidationError("ملف الصورة فارغ أو لم يصل إلى الخادم.")

    content_type = getattr(uploaded, "content_type", "") or "application/octet-stream"
    name = safe_image_filename(uploaded, default_stem=default_stem)

    if len(data) > reencode_over_bytes:
        try:
            from PIL import Image, UnidentifiedImageError

            with Image.open(BytesIO(data)) as im:
                im = im.convert("RGB")
                w, h = im.size
                resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
                if max(w, h) > max_edge:
                    scale = max_edge / float(max(w, h))
                    im = im.resize(
                        (max(1, int(w * scale)), max(1, int(h * scale))),
                        resample,
                    )
                out = BytesIO()
                im.save(out, format="JPEG", quality=jpeg_quality, optimize=True)
                data = out.getvalue()
            name = safe_image_filename(uploaded, default_stem=default_stem, force_ext="jpg")
            content_type = "image/jpeg"
        except UnidentifiedImageError as exc:
            raise DRFValidationError("تعذر قراءة الصورة. استخدم ملف JPG أو PNG صالح.") from exc
        except Exception:
            pass

    buf = BytesIO(data)
    return InMemoryUploadedFile(
        buf,
        field_name=field_name,
        name=name,
        content_type=content_type,
        size=len(data),
        charset=None,
    )
