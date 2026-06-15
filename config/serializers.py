from rest_framework import serializers

from academics.models import ClassGradebook, SchoolClass, Student, Subject, SubjectGrade
from assignments.models import Homework, HomeworkSubmission, Quiz, QuizQuestion, QuizSubmission
from content.models import (
    Accreditation,
    Activity,
    Alumni,
    NewsItem,
    Policy,
    Program,
    SchoolStat,
    SchoolValue,
)
from finance.models import PaymentNotice, PaymentStatus, StudentFeeBalance
from staff.models import TeacherClassAssignment, TeacherProfile
from accounts.models import User
from accounts.utils import create_auto_user, next_numeric_username


class SchoolClassSerializer(serializers.ModelSerializer):
    gradeLevel = serializers.CharField(source="grade_level", read_only=True)
    studentCount = serializers.IntegerField(source="student_count", read_only=True)

    class Meta:
        model = SchoolClass
        fields = ["id", "name", "gradeLevel", "section", "studentCount"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class SchoolClassWriteSerializer(serializers.ModelSerializer):
    gradeLevel = serializers.CharField(source="grade_level")
    name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = SchoolClass
        fields = ["id", "name", "gradeLevel", "section"]

    def validate(self, attrs):
        grade = attrs.get("grade_level", "").strip()
        section = attrs.get("section", "").strip()
        if not grade:
            raise serializers.ValidationError({"gradeLevel": "الصف الدراسي مطلوب"})
        if not section:
            raise serializers.ValidationError({"section": "الشعبة مطلوبة"})
        attrs["grade_level"] = grade
        attrs["section"] = section
        attrs["name"] = attrs.get("name") or f"{grade} - {section}"
        qs = SchoolClass.objects.filter(grade_level=grade, section=section)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {"section": f"الشعبة {section} موجودة مسبقاً في {grade}"}
            )
        return attrs

    def to_representation(self, instance):
        return SchoolClassSerializer(instance).data


class SubjectSerializer(serializers.ModelSerializer):
    teacherCount = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = ["id", "name", "teacherCount"]

    def get_teacherCount(self, obj):
        return obj.teachers.count()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class StudentSerializer(serializers.ModelSerializer):
    grade = serializers.CharField(source="grade_level")
    studentNumber = serializers.CharField(source="student_number", required=False)
    classId = serializers.PrimaryKeyRelatedField(
        source="school_class", queryset=SchoolClass.objects.all(), allow_null=True, required=False
    )
    username = serializers.SerializerMethodField()
    generatedPassword = serializers.SerializerMethodField()
    paymentStatus = serializers.SerializerMethodField()
    feesPaid = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id",
            "name",
            "grade",
            "section",
            "studentNumber",
            "classId",
            "username",
            "generatedPassword",
            "documents",
            "paymentStatus",
            "feesPaid",
            "balance",
            "is_active",
        ]
        read_only_fields = ["studentNumber", "username", "generatedPassword"]

    def get_username(self, obj):
        return obj.parent.username if obj.parent_id else None

    def get_generatedPassword(self, obj):
        return getattr(obj, "_generated_password", None)

    def validate(self, attrs):
        school_class = attrs.get("school_class")
        if school_class:
            attrs["grade_level"] = school_class.grade_level or school_class.name
            attrs["section"] = school_class.section
        elif self.instance is None:
            raise serializers.ValidationError({"classId": "يجب اختيار فصل وشعبة"})
        return attrs

    def create(self, validated_data):
        student_number = validated_data.get("student_number") or next_numeric_username()
        while Student.objects.filter(student_number=student_number).exists():
            student_number = next_numeric_username()

        parent, password = create_auto_user(
            name=validated_data["name"],
            role=User.Role.PARENT,
            username=student_number,
        )
        validated_data["parent"] = parent
        validated_data["student_number"] = student_number
        student = Student.objects.create(**validated_data)
        student._generated_password = password
        return student

    def get_paymentStatus(self, obj):
        latest = obj.payment_notices.order_by("-date").first()
        if latest:
            return latest.status
        if hasattr(obj, "fee_balance"):
            return PaymentStatus.APPROVED if obj.fee_balance.fees_paid else PaymentStatus.PENDING
        return PaymentStatus.PENDING

    def get_feesPaid(self, obj):
        if hasattr(obj, "fee_balance"):
            return obj.fee_balance.fees_paid
        return False

    def get_balance(self, obj):
        if hasattr(obj, "fee_balance"):
            fb = obj.fee_balance
            return {"total": float(fb.total), "paid": float(fb.paid), "remaining": float(fb.remaining)}
        return {"total": 0, "paid": 0, "remaining": 0}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        if data.get("classId") is not None:
            data["classId"] = str(data["classId"])
        return data


class SubjectGradeSerializer(serializers.ModelSerializer):
    maxScore = serializers.DecimalField(source="max_score", max_digits=5, decimal_places=2)

    class Meta:
        model = SubjectGrade
        fields = ["id", "subject", "score", "maxScore", "note"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["score"] = float(data["score"])
        data["maxScore"] = float(data["maxScore"])
        return data


class ClassGradebookSerializer(serializers.ModelSerializer):
    classId = serializers.PrimaryKeyRelatedField(source="school_class", read_only=True)
    studentId = serializers.PrimaryKeyRelatedField(source="student", read_only=True)

    class Meta:
        model = ClassGradebook
        fields = ["id", "studentId", "classId", "score", "note"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["studentId"] = str(data["studentId"])
        data["classId"] = str(data["classId"])
        if data["score"] is not None:
            data["score"] = float(data["score"])
        return data


class ClassStudentSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    grade = serializers.JSONField()
    note = serializers.CharField()


class TeacherProfileSerializer(serializers.ModelSerializer):
    userId = serializers.PrimaryKeyRelatedField(
        source="user", queryset=User.objects.all(),
        allow_null=True, required=False
    )
    username = serializers.SerializerMethodField()
    generatedPassword = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()
    subjects = serializers.SerializerMethodField()
    subjectIds = serializers.SerializerMethodField()
    imageUrl = serializers.SerializerMethodField()
    imageGradient = serializers.CharField(source="image_gradient", required=False, allow_blank=True)
    classIds = serializers.SerializerMethodField()

    class Meta:
        model = TeacherProfile
        fields = [
            "id",
            "userId",
            "username",
            "generatedPassword",
            "name",
            "subject",
            "subjects",
            "subjectIds",
            "experience",
            "bio",
            "image",
            "imageUrl",
            "imageGradient",
            "is_public",
            "classIds",
        ]
        extra_kwargs = {"image": {"write_only": True}}

    def get_imageUrl(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = obj.image.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def _subject_names(self, obj):
        return [s.name for s in obj.teaching_subjects.all()]

    def get_subject(self, obj):
        return "، ".join(self._subject_names(obj))

    def get_subjects(self, obj):
        return self._subject_names(obj)

    def get_subjectIds(self, obj):
        return [str(s.id) for s in obj.teaching_subjects.all()]

    def get_username(self, obj):
        return obj.user.username if obj.user_id else None

    def get_generatedPassword(self, obj):
        return getattr(obj, "_generated_password", None)

    def get_classIds(self, obj):
        return [str(a.school_class_id) for a in obj.class_assignments.select_related("school_class")]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        if data.get("userId") is not None:
            data["userId"] = str(data["userId"])
        data.pop("image", None)
        return data


class TeacherWriteSerializer(serializers.ModelSerializer):
    userId = serializers.PrimaryKeyRelatedField(
        source="user",
        queryset=User.objects.all(),
        allow_null=True,
        required=False,
    )
    subjectIds = serializers.PrimaryKeyRelatedField(
        source="teaching_subjects",
        queryset=Subject.objects.all(),
        many=True,
    )
    subject = serializers.SerializerMethodField()
    subjects = serializers.SerializerMethodField()
    imageGradient = serializers.CharField(source="image_gradient", required=False, allow_blank=True)
    classIds = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)

    class Meta:
        model = TeacherProfile
        fields = [
            "id",
            "userId",
            "name",
            "subject",
            "subjects",
            "subjectIds",
            "experience",
            "bio",
            "image",
            "imageGradient",
            "classIds",
        ]
        extra_kwargs = {"image": {"write_only": True}}

    def get_subject(self, obj):
        return "، ".join(s.name for s in obj.teaching_subjects.all())

    def get_subjects(self, obj):
        return [s.name for s in obj.teaching_subjects.all()]

    def validate(self, attrs):
        if self.instance is None and not attrs.get("teaching_subjects"):
            raise serializers.ValidationError({"subjectIds": "يجب اختيار مادة واحدة على الأقل"})
        return attrs

    def _set_classes(self, teacher, class_ids):
        TeacherClassAssignment.objects.filter(teacher=teacher).delete()
        for class_id in class_ids or []:
            TeacherClassAssignment.objects.create(teacher=teacher, school_class_id=class_id)

    def create(self, validated_data):
        validated_data.pop("user", None)
        class_ids = validated_data.pop("classIds", [])
        subjects = validated_data.pop("teaching_subjects", [])
        user, password = create_auto_user(
            name=validated_data["name"],
            role=User.Role.TEACHER,
        )
        validated_data["user"] = user
        teacher = TeacherProfile.objects.create(**validated_data)
        teacher.teaching_subjects.set(subjects)
        self._set_classes(teacher, class_ids)
        teacher._generated_password = password
        return teacher

    def update(self, instance, validated_data):
        class_ids = validated_data.pop("classIds", None)
        subjects = validated_data.pop("teaching_subjects", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if subjects is not None:
            instance.teaching_subjects.set(subjects)
        if class_ids is not None:
            self._set_classes(instance, class_ids)
        return instance

    def to_representation(self, instance):
        return TeacherProfileSerializer(instance).data


class QuizQuestionSerializer(serializers.ModelSerializer):
    correctIndex = serializers.IntegerField(source="correct_index")

    class Meta:
        model = QuizQuestion
        fields = ["id", "prompt", "options", "correctIndex", "order"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class HomeworkSerializer(serializers.ModelSerializer):
    classId = serializers.PrimaryKeyRelatedField(source="school_class", queryset=SchoolClass.objects.all())
    teacherId = serializers.PrimaryKeyRelatedField(
        source="teacher", queryset=TeacherProfile.objects.all(), required=False
    )
    dueDate = serializers.DateField(source="due_date", format="%Y-%m-%d")
    createdAt = serializers.DateTimeField(source="created_at", format="%Y-%m-%d", read_only=True)

    class Meta:
        model = Homework
        fields = ["id", "classId", "teacherId", "title", "description", "dueDate", "status", "createdAt"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["classId"] = str(data["classId"])
        data["teacherId"] = str(data["teacherId"])
        return data


class HomeworkSubmissionSerializer(serializers.ModelSerializer):
    homeworkId = serializers.PrimaryKeyRelatedField(source="homework", queryset=Homework.objects.all())
    studentId = serializers.PrimaryKeyRelatedField(source="student", queryset=Student.objects.all())
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True)

    class Meta:
        model = HomeworkSubmission
        fields = ["id", "homeworkId", "studentId", "content", "submittedAt"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["homeworkId"] = str(data["homeworkId"])
        data["studentId"] = str(data["studentId"])
        return data


class QuizSerializer(serializers.ModelSerializer):
    classId = serializers.PrimaryKeyRelatedField(source="school_class", queryset=SchoolClass.objects.all())
    teacherId = serializers.PrimaryKeyRelatedField(
        source="teacher", queryset=TeacherProfile.objects.all(), required=False
    )
    dueDate = serializers.DateField(source="due_date", format="%Y-%m-%d")
    startAt = serializers.DateTimeField(source="start_at")
    durationMinutes = serializers.IntegerField(source="duration_minutes")
    createdAt = serializers.DateTimeField(source="created_at", format="%Y-%m-%d", read_only=True)
    questions = QuizQuestionSerializer(many=True, required=False)

    class Meta:
        model = Quiz
        fields = [
            "id", "classId", "teacherId", "title", "description", "dueDate",
            "startAt", "durationMinutes", "status", "questions", "createdAt",
        ]

    def create(self, validated_data):
        questions_data = validated_data.pop("questions", [])
        quiz = Quiz.objects.create(**validated_data)
        for i, q in enumerate(questions_data):
            QuizQuestion.objects.create(quiz=quiz, order=i, **q)
        return quiz

    def update(self, instance, validated_data):
        questions_data = validated_data.pop("questions", None)
        instance = super().update(instance, validated_data)
        if questions_data is not None:
            instance.questions.all().delete()
            for i, q in enumerate(questions_data):
                QuizQuestion.objects.create(quiz=instance, order=i, **q)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["classId"] = str(data["classId"])
        data["teacherId"] = str(data["teacherId"])
        return data


class QuizSubmissionSerializer(serializers.ModelSerializer):
    quizId = serializers.PrimaryKeyRelatedField(source="quiz", queryset=Quiz.objects.all())
    studentId = serializers.PrimaryKeyRelatedField(source="student", queryset=Student.objects.all())
    maxScore = serializers.DecimalField(source="max_score", max_digits=5, decimal_places=2)
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True)
    timeSpentSeconds = serializers.IntegerField(source="time_spent_seconds")

    class Meta:
        model = QuizSubmission
        fields = ["id", "quizId", "studentId", "answers", "score", "maxScore", "submittedAt", "timeSpentSeconds"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["quizId"] = str(data["quizId"])
        data["studentId"] = str(data["studentId"])
        data["score"] = float(data["score"])
        data["maxScore"] = float(data["maxScore"])
        return data


class PaymentNoticeSerializer(serializers.ModelSerializer):
    studentName = serializers.CharField(source="student.name", read_only=True)

    class Meta:
        model = PaymentNotice
        fields = ["id", "studentName", "amount", "date", "status", "note"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["amount"] = float(data["amount"])
        data["date"] = str(data["date"])
        return data


class FinanceNoticeSerializer(serializers.Serializer):
    id = serializers.CharField()
    studentName = serializers.CharField()
    amount = serializers.FloatField()
    status = serializers.CharField()
    date = serializers.CharField()


class NewsItemSerializer(serializers.ModelSerializer):
    imageUrl = serializers.SerializerMethodField()

    class Meta:
        model = NewsItem
        fields = [
            "id", "title", "description", "body", "date", "category",
            "gradient", "featured", "image", "imageUrl",
        ]
        extra_kwargs = {"image": {"write_only": True}}

    def get_imageUrl(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = obj.image.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["date"] = str(data["date"])
        data.pop("image", None)
        return data


class ProgramSerializer(serializers.ModelSerializer):
    desc = serializers.CharField(source="description")

    class Meta:
        model = Program
        fields = ["id", "title", "grades", "desc", "features", "accent"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class ActivitySerializer(serializers.ModelSerializer):
    desc = serializers.CharField(source="description")

    class Meta:
        model = Activity
        fields = ["id", "title", "desc"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class AlumniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alumni
        fields = ["id", "name", "year", "achievement"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class PolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = Policy
        fields = ["id", "title", "text"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class AccreditationSerializer(serializers.ModelSerializer):
    desc = serializers.CharField(source="description")

    class Meta:
        model = Accreditation
        fields = ["id", "name", "desc"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class SchoolStatSerializer(serializers.ModelSerializer):
    iconBg = serializers.CharField(source="icon_bg")
    iconColor = serializers.CharField(source="icon_color")
    iconName = serializers.CharField(source="icon_name")

    class Meta:
        model = SchoolStat
        fields = ["id", "label", "value", "iconName", "iconBg", "iconColor"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = instance.key
        return data


class SchoolValueSerializer(serializers.ModelSerializer):
    desc = serializers.CharField(source="description")
    num = serializers.CharField(source="number")

    class Meta:
        model = SchoolValue
        fields = ["id", "title", "desc", "num"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class ParentAlertSerializer(serializers.Serializer):
    id = serializers.CharField()
    text = serializers.CharField()
    type = serializers.CharField()


class ParentChildSerializer(serializers.Serializer):
    parentUserId = serializers.CharField()
    studentId = serializers.CharField()
    classId = serializers.CharField()
    name = serializers.CharField()
