from rest_framework import serializers


class HealthCheckSerializer(serializers.Serializer):
    db = serializers.BooleanField()
    cache = serializers.BooleanField()
    status = serializers.CharField()


class PublishJobStatusSerializer(serializers.Serializer):
    exists = serializers.BooleanField()
    job_id = serializers.IntegerField(required=False, allow_null=True)
    status = serializers.CharField(allow_blank=True)
    status_display = serializers.CharField(allow_blank=True)
    progress_percent = serializers.IntegerField()
    step_label = serializers.CharField(allow_blank=True)
    error_message = serializers.CharField(allow_blank=True)
    chapter_status = serializers.CharField()
    chapter_status_display = serializers.CharField()


class ExtractionRecordSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    source_filename = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    is_finished = serializers.BooleanField()
    cancel_requested = serializers.BooleanField()
    image_width = serializers.IntegerField()
    image_height = serializers.IntegerField()
    attempt_count = serializers.IntegerField()
    duration_ms = serializers.IntegerField()
    selected_method = serializers.CharField(allow_blank=True)
    raw_payload = serializers.CharField(allow_blank=True)
    parsed_reader_id = serializers.CharField(allow_blank=True)
    parsed_yyyymmdd = serializers.CharField(allow_blank=True)
    is_valid = serializers.BooleanField()
    error_message = serializers.CharField(allow_blank=True)
    advanced_extraction = serializers.BooleanField()
    visible_previews = serializers.ListField(child=serializers.DictField(), required=False)
    blind_direct = serializers.DictField(required=False, allow_null=True)
    blind_advanced = serializers.DictField(required=False, allow_null=True)
    process_log = serializers.ListField(child=serializers.DictField(), required=False)
