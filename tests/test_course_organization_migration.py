import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_teaching_course_migration_preserves_populated_cohorts_and_history():
    old_target = [("liveclassroom", "0004_liveactivity_runtime_state")]
    new_target = [("liveclassroom", "0005_teaching_course_organization")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(old_target)
        old_apps = executor.loader.project_state(old_target).apps
        user = old_apps.get_model("auth", "User").objects.create(username="migration-owner")
        course = old_apps.get_model("liveclassroom", "Course").objects.create(
            title="Existing class", slug="existing-class", created_by_id=user.id
        )
        membership = old_apps.get_model("liveclassroom", "CourseMembership").objects.create(
            course_id=course.id, user_id=user.id, role="teacher"
        )
        session = old_apps.get_model("liveclassroom", "LiveSession").objects.create(
            title="Existing session", course_id=course.id, teacher_id=user.id
        )

        executor = MigrationExecutor(connection)
        executor.migrate(new_target)
        new_apps = executor.loader.project_state(new_target).apps
        new_course = new_apps.get_model("liveclassroom", "Course").objects.get(pk=course.id)
        assert new_course.title == "Existing class"
        assert new_course.teaching_course_id is None
        assert new_apps.get_model("liveclassroom", "CourseMembership").objects.filter(pk=membership.id).exists()
        assert new_apps.get_model("liveclassroom", "LiveSession").objects.get(pk=session.id).course_id == course.id
    finally:
        MigrationExecutor(connection).migrate(new_target)
