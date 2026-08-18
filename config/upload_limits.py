from django.core.validators import FileExtensionValidator

ALLOWED_UPLOAD_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".txt",
    ".zip",
}

ALLOWED_UPLOAD_EXTENSION_NAMES = sorted(ext.lstrip(".") for ext in ALLOWED_UPLOAD_EXTENSIONS)

upload_file_validator = FileExtensionValidator(
    allowed_extensions=ALLOWED_UPLOAD_EXTENSION_NAMES,
    message="نوع الملف غير مسموح",
)

IMAGE_UPLOAD_EXTENSION_NAMES = ["jpg", "jpeg", "png", "gif", "webp", "bmp"]

upload_image_validator = FileExtensionValidator(
    allowed_extensions=IMAGE_UPLOAD_EXTENSION_NAMES,
    message="نوع الصورة غير مسموح",
)
