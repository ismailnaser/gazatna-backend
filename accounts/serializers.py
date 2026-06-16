from rest_framework import serializers

from accounts.models import User
from accounts.roles import ADMIN_ROLES, SUPER_ADMIN_ROLE


class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "username", "email", "role", "status"]
        read_only_fields = ["id"]

    def get_name(self, obj):
        return obj.display_name

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class UserCreateSerializer(serializers.ModelSerializer):
    name = serializers.CharField(write_only=True)
    username = serializers.CharField(required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ["id", "name", "username", "email", "role", "status", "password"]

    def validate_role(self, value):
        allowed = {r for r in ADMIN_ROLES}
        if value not in allowed:
            raise serializers.ValidationError("يجب اختيار دور إداري صالح")
        return value

    def validate_username(self, value):
        username = value.strip()
        if not username:
            raise serializers.ValidationError("اسم المستخدم مطلوب")
        qs = User.objects.filter(username=username)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("اسم المستخدم مستخدم مسبقاً")
        return username

    def validate(self, attrs):
        if self.instance is None:
            if not attrs.get("username"):
                raise serializers.ValidationError({"username": "اسم المستخدم مطلوب"})
            if not attrs.get("role"):
                attrs["role"] = SUPER_ADMIN_ROLE
        return attrs

    def create(self, validated_data):
        name = validated_data.pop("name")
        username = validated_data.pop("username").strip()
        password = validated_data.pop("password", "")
        if not password:
            raise serializers.ValidationError({"password": "كلمة المرور مطلوبة"})
        email = (validated_data.pop("email", None) or "").strip().lower()
        if not email:
            email = f"{username}@school.local"
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=name,
            password=password,
            **validated_data,
        )
        return user

    def update(self, instance, validated_data):
        name = validated_data.pop("name", None)
        username = validated_data.pop("username", None)
        password = validated_data.pop("password", None)
        if "email" in validated_data:
            validated_data["email"] = validated_data["email"].lower()
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if name:
            instance.first_name = name
        if username:
            instance.username = username.strip()
        if password:
            instance.set_password(password)
        instance.save()
        return instance

    def to_representation(self, instance):
        return UserSerializer(instance).data
