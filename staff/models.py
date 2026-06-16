from django.conf import settings
from django.db import models


class TeacherProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teacher_profile",
    )
    name = models.CharField(max_length=200)
    teaching_subjects = models.ManyToManyField(
        "academics.Subject",
        related_name="teachers",
        blank=True,
    )
    experience = models.TextField(blank=True)
    bio = models.TextField(blank=True)
    image = models.ImageField(upload_to="teachers/", blank=True, null=True)
    image_gradient = models.CharField(max_length=200, blank=True)
    is_public = models.BooleanField(default=True)

    class Meta:
        verbose_name = "معلم"
        verbose_name_plural = "المعلمون"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.image:
            return
        try:
            from PIL import Image
        except Exception:
            return
        try:
            img_path = self.image.path
            with Image.open(img_path) as im:
                im = im.convert("RGB")
                w, h = im.size
                side = min(w, h)
                left = (w - side) // 2
                top = (h - side) // 2
                im = im.crop((left, top, left + side, top + side))
                im = im.resize((512, 512), Image.Resampling.LANCZOS)
                im.save(img_path, quality=88, optimize=True)
        except Exception:
            # If processing fails, keep original upload.
            return


class TeacherClassAssignment(models.Model):
    teacher = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name="class_assignments")
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.CASCADE, related_name="teacher_assignments")

    class Meta:
        unique_together = [("teacher", "school_class")]
        verbose_name = "تعيين معلم لصف"
        verbose_name_plural = "تعيينات المعلمين"
