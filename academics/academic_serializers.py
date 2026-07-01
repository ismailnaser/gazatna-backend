from rest_framework import serializers

from academics.academic_services import serialize_academic_year, serialize_promotion_policy
from academics.models import AcademicTerm, AcademicYear, PromotionPolicy


class AcademicTermWriteSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField(max_length=100)
    sortOrder = serializers.IntegerField(min_value=1)
    startDate = serializers.DateField()
    endDate = serializers.DateField()
    isCurrent = serializers.BooleanField(required=False, default=False)


class PromotionPolicySerializer(serializers.ModelSerializer):
    evaluationScope = serializers.ChoiceField(
        source="evaluation_scope",
        choices=[choice[0] for choice in PromotionPolicy.EVALUATION_SCOPE_CHOICES],
        required=False,
    )
    yearCalculationMethod = serializers.ChoiceField(
        source="year_calculation_method",
        choices=[choice[0] for choice in PromotionPolicy.YEAR_CALCULATION_CHOICES],
        required=False,
    )
    evaluationTermId = serializers.PrimaryKeyRelatedField(
        source="evaluation_term",
        queryset=AcademicTerm.objects.all(),
        allow_null=True,
        required=False,
    )
    passRule = serializers.ChoiceField(
        source="pass_rule",
        choices=[choice[0] for choice in PromotionPolicy.PASS_RULE_CHOICES],
    )
    passMinimumCount = serializers.IntegerField(source="pass_minimum_count", min_value=1, required=False)
    requiredSubjects = serializers.ListField(
        child=serializers.CharField(max_length=100),
        source="required_subjects",
        required=False,
    )
    passScoreRatio = serializers.DecimalField(
        source="pass_score_ratio",
        max_digits=4,
        decimal_places=3,
        min_value=0,
        max_value=1,
        required=False,
    )
    passPromotionMode = serializers.ChoiceField(
        source="pass_promotion_mode",
        choices=[choice[0] for choice in PromotionPolicy.PROMOTION_MODE_CHOICES],
        required=False,
    )
    failHandlingMode = serializers.ChoiceField(
        source="fail_handling_mode",
        choices=[choice[0] for choice in PromotionPolicy.FAILURE_MODE_CHOICES],
        required=False,
    )

    class Meta:
        model = PromotionPolicy
        fields = [
            "evaluationScope",
            "yearCalculationMethod",
            "evaluationTermId",
            "passRule",
            "passMinimumCount",
            "requiredSubjects",
            "passScoreRatio",
            "passPromotionMode",
            "failHandlingMode",
        ]

    def update(self, instance, validated_data):
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.is_configured = True
        instance.save()
        return instance

    def to_representation(self, instance):
        return serialize_promotion_policy(instance)


class AcademicYearWriteSerializer(serializers.ModelSerializer):
    startDate = serializers.DateField(source="start_date")
    endDate = serializers.DateField(source="end_date")
    isActive = serializers.BooleanField(source="is_active", required=False)
    terms = AcademicTermWriteSerializer(many=True, required=False)

    class Meta:
        model = AcademicYear
        fields = ["id", "name", "startDate", "endDate", "status", "isActive", "terms"]

    def validate(self, attrs):
        start = attrs.get("start_date")
        end = attrs.get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError({"endDate": "تاريخ النهاية يجب أن يكون بعد البداية"})
        name = attrs.get("name")
        if name is not None:
            attrs["name"] = str(name).strip()
            if not attrs["name"]:
                raise serializers.ValidationError({"name": "اسم السنة الدراسية مطلوب"})
        return attrs

    def create(self, validated_data):
        terms_data = validated_data.pop("terms", None)
        year = AcademicYear.objects.create(**validated_data)
        if terms_data:
            self._sync_terms(year, terms_data)
        return year

    def update(self, instance, validated_data):
        terms_data = validated_data.pop("terms", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if terms_data is not None:
            self._sync_terms(instance, terms_data)
        return instance

    def _sync_terms(self, year, terms_data):
        from academics.academic_services import validate_academic_terms

        validate_academic_terms(year, terms_data)
        kept_ids = []
        for item in terms_data:
            term_id = str(item.get("id") or "").strip()
            payload = {
                "name": item["name"],
                "sort_order": item["sortOrder"],
                "start_date": item["startDate"],
                "end_date": item["endDate"],
            }
            if term_id.isdigit():
                term = AcademicTerm.objects.filter(id=term_id, academic_year=year).first()
                if term:
                    for key, value in payload.items():
                        setattr(term, key, value)
                    term.save()
                    kept_ids.append(term.id)
                    continue
            term = AcademicTerm.objects.create(academic_year=year, **payload)
            kept_ids.append(term.id)

        AcademicTerm.objects.filter(academic_year=year).exclude(id__in=kept_ids).delete()

        current = next((item for item in terms_data if item.get("isCurrent")), None)
        if current:
            sort_order = current.get("sortOrder")
            term = AcademicTerm.objects.filter(academic_year=year, sort_order=sort_order).first()
            if term:
                from academics.academic_services import set_current_academic_term

                set_current_academic_term(term)
        elif not AcademicTerm.objects.filter(academic_year=year, is_current=True).exists():
            first = AcademicTerm.objects.filter(academic_year=year).order_by("sort_order").first()
            if first:
                from academics.academic_services import set_current_academic_term

                set_current_academic_term(first)

    def to_representation(self, instance):
        return serialize_academic_year(instance)
