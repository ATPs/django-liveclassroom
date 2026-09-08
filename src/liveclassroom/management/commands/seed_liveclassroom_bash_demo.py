"""Install the public, read-only Bash-for-beginners teaching examples."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import uuid
from copy import deepcopy

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.templatetags.static import static
from django.utils import timezone

from liveclassroom.models import (
    ActivityDefinition,
    ActivityRunRevision,
    ClassroomAsset,
    Course,
    DemoLesson,
    Flow,
    FlowStep,
    LiveActivity,
    LiveSession,
    Participant,
    Submission,
    SubmissionRevision,
)
from liveclassroom.services.classroom import revise_activity_definition

_DEMO_SLUG = "bash-for-linux-beginners"
_DEMO_USERNAME = "liveclassroom-demo"


def _step_key(language: str, key: str) -> uuid.UUID:
    """Keep demo matching independent from the title shown to teachers."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"liveclassroom:{_DEMO_SLUG}:{language}:{key}")


def _copy(*, en: str, zh: str) -> dict[str, str]:
    return {"en": en, "zh-Hans": zh}


_TEXT = {
    "course": _copy(en="LiveClassroom public demos", zh="LiveClassroom 公共示例"),
    "course_description": _copy(
        en="Read-only example lessons. Use a demo to create your own independent classroom.",
        zh="只读示例教案。使用示例会创建属于你的独立课堂。",
    ),
    "lesson": _copy(en="Bash for Linux beginners — 20-minute live class", zh="Linux 初学者 Bash 入门 — 20 分钟课堂"),
    "description": _copy(
        en="A teacher-led, bilingual starter lesson. It uses a safe browser-only Bash simulator; it never runs shell commands on the server.",
        zh="教师带领的双语入门课，使用仅在浏览器中运行的安全 Bash 模拟器；不会在服务器上执行 shell 命令。",
    ),
    "ready": _copy(en="Bash beginners — ready to teach", zh="Bash 初学者 — 待开始"),
    "live": _copy(en="Bash beginners — live example", zh="Bash 初学者 — 进行中示例"),
    "ended": _copy(en="Bash beginners — finished example", zh="Bash 初学者 — 已结束示例"),
    "cheatsheet": _copy(en="Bash starter cheat sheet", zh="Bash 入门速查表"),
}


def _lesson_steps(language: str, asset: ClassroomAsset) -> list[tuple[str, str, dict]]:
    zh = language == "zh-Hans"

    def text(en: str, cn: str) -> str:
        return cn if zh else en
    filesystem = {
        "/home/student/README.txt": text(
            "Welcome! Use pwd, ls, cd, cat and echo. This is a simulated filesystem.",
            "欢迎！使用 pwd、ls、cd、cat 和 echo。这是模拟文件系统。",
        ),
        "/home/student/projects/hello.txt": text("Hello from Bash practice!", "来自 Bash 练习的问候！"),
        "/home/student/notes/today.txt": text("Commands describe where you are and what is here.", "命令用来描述你在哪里，以及这里有什么。"),
    }
    return [
        (
            "welcome",
            text("Welcome and goal (1 min)", "欢迎与目标（1 分钟）"),
            {
                "type_key": "liveclassroom.markdown",
                "definition": {
                    "markdown": text(
                        "# Welcome to Bash\n\n**Goal:** read your location, list files, move safely, and read a text file.\n\nThis is a 20-minute teacher-led starter. Every command in the practice is simulated in your browser; it does not access your computer or the server.",
                        "# 欢迎学习 Bash\n\n**目标：** 知道自己在哪里、列出文件、安全进入文件夹，并读取文本文件。\n\n这是 20 分钟教师带领的入门课。练习中的每条命令都只在浏览器中模拟，不会访问你的电脑或服务器。",
                    )
                },
            },
        ),
        (
            "confidence_poll",
            text("Starting point: have you used a terminal? (1 min)", "起点调查：你用过终端吗？（1 分钟）"),
            {
                "type_key": "liveclassroom.poll",
                "definition": {
                    "prompt": text("How familiar are you with a terminal?", "你对终端有多熟悉？"),
                    "options": [
                        {"id": "new", "text": text("New to it", "第一次使用")},
                        {"id": "some", "text": text("I have tried it", "我试过")},
                        {"id": "often", "text": text("I use it often", "我经常使用")},
                    ],
                },
            },
        ),
        (
            "word_cloud",
            text("What do you want to do with Linux? (1 min)", "你想用 Linux 做什么？（1 分钟）"),
            {
                "type_key": "liveclassroom.word_cloud",
                "definition": {
                    "prompt": text(
                        "What would you like to do with Linux? Write one or two words.",
                        "你想用 Linux 做什么？写一到两个词。",
                    ),
                    "max_length": 80,
                },
            },
        ),
        (
            "terminal_map",
            text("Read a command before running it (1 min)", "运行前先读懂命令（1 分钟）"),
            {
                "type_key": "liveclassroom.media",
                "definition": {
                    "url": static(
                        "liveclassroom/demo/bash-command-flow-zh-Hans.svg"
                        if zh else "liveclassroom/demo/bash-command-flow.svg"
                    ),
                    "media_type": "image",
                    "caption": text(
                        "A command has a program name and optional arguments. In this class every command stays inside the simulator.",
                        "命令由程序名和可选参数组成。本课所有命令都只在模拟器中运行。",
                    ),
                },
            },
        ),
        (
            "cheatsheet",
            text("Keep this command cheat sheet (1 min)", "保存这份命令速查表（1 分钟）"),
            {
                "type_key": "liveclassroom.file",
                "asset": asset,
                "definition": {
                    "asset_id": str(asset.public_id),
                    "file_kind": "markdown",
                    "caption": text("A short reference for this class.", "本课的简短参考资料。"),
                },
            },
        ),
        (
            "simulator",
            text("Guided Bash practice (5 min)", "引导式 Bash 练习（5 分钟）"),
            {
                "type_key": "liveclassroom.bash_simulator",
                "definition": {
                    "prompt": text(
                        "In the simulated terminal: run pwd, ls, cat README.txt, then cd projects. When the final prompt shows /home/student/projects, explicitly confirm your completed practice.",
                        "在模拟终端中依次运行 pwd、ls、cat README.txt，然后 cd projects。当最后提示符显示 /home/student/projects 时，请明确确认已完成练习。",
                    ),
                    "filesystem": filesystem,
                    "initial_directory": "/home/student",
                    "completion": {
                        "required_commands": ["pwd", "ls", "cat", "cd"],
                        "required_directory": "/home/student/projects",
                    },
                    "max_transcript_entries": 16,
                },
            },
        ),
        (
            "timer",
            text("Pair check: explain pwd and ls (2 min)", "同伴讨论：解释 pwd 和 ls（2 分钟）"),
            {
                "type_key": "liveclassroom.timer",
                "definition": {"duration_seconds": 120, "auto_start": False, "label": text("Pair discussion", "同伴讨论")},
            },
        ),
        (
            "true_false",
            text("Safety check (1 min)", "安全检查（1 分钟）"),
            {
                "type_key": "liveclassroom.true_false",
                "definition": {
                    "prompt": text("pwd changes the current folder.", "pwd 会改变当前文件夹。"),
                    "answer": "false",
                    "explanation": text(
                        "False. pwd prints the current folder; cd changes folders.",
                        "错误。pwd 显示当前文件夹；cd 才会切换文件夹。",
                    ),
                },
            },
        ),
        (
            "multiple_choice",
            text("Choose safe exploration commands (1 min)", "选择安全探索命令（1 分钟）"),
            {
                "type_key": "liveclassroom.multiple_choice",
                "definition": {
                    "prompt": text("Which commands are available in this beginner simulator?", "初学者模拟器中可以使用哪些命令？"),
                    "options": [
                        {"id": "pwd", "text": text("pwd — print the current directory", "pwd — 显示当前目录")},
                        {"id": "ls", "text": text("ls — list files and folders", "ls — 列出文件和文件夹")},
                        {"id": "rm", "text": text("rm — remove files (not available here)", "rm — 删除文件（此处不可用）")},
                        {"id": "cat", "text": text("cat — read a text file", "cat — 读取文本文件")},
                    ],
                    "answer": ["pwd", "ls", "cat"],
                },
            },
        ),
        (
            "single_choice",
            text("Find your location (1 min)", "找到当前位置（1 分钟）"),
            {
                "type_key": "liveclassroom.single_choice",
                "definition": {
                    "prompt": text("Which command prints the current directory?", "哪条命令会显示当前目录？"),
                    "options": [
                        {"id": "pwd", "text": text("pwd — print the current directory", "pwd — 显示当前目录")},
                        {"id": "ls", "text": text("ls — list files and folders", "ls — 列出文件和文件夹")},
                        {"id": "cat", "text": text("cat — read a text file", "cat — 读取文本文件")},
                    ],
                    "answer": "pwd",
                },
            },
        ),
        (
            "numeric",
            text("Estimate the practice steps (1 min)", "估计练习步骤数（1 分钟）"),
            {
                "type_key": "liveclassroom.numeric",
                "definition": {"prompt": text("How many command names did the guided task require?", "引导任务要求了几种命令？"), "label": text("Number of command names", "命令名称数量"), "minimum": 0, "maximum": 10, "step": 1},
            },
        ),
        (
            "rating",
            text("Rate your confidence (1 min)", "评价你的信心（1 分钟）"),
            {
                "type_key": "liveclassroom.rating",
                "definition": {"prompt": text("Rate your confidence using pwd and ls", "请评价你使用 pwd 和 ls 的信心"), "minimum": 1, "maximum": 5, "step": 1, "minimum_label": text("Not confident yet", "还不太有信心"), "maximum_label": text("Very confident", "非常有信心")},
            },
        ),
        (
            "ranking",
            text("Order the safe workflow (1 min)", "排列安全操作顺序（1 分钟）"),
            {
                "type_key": "liveclassroom.ranking",
                "definition": {
                    "prompt": text("Order the steps for exploring a new folder.", "请排列探索新文件夹的步骤。"),
                    "options": [
                        {"id": "pwd", "text": text("pwd — see where you are", "pwd — 查看当前位置")},
                        {"id": "ls", "text": text("ls — see what is here", "ls — 查看这里有什么")},
                        {"id": "cd", "text": text("cd folder — move deliberately", "cd 文件夹 — 有意识地进入文件夹")},
                    ],
                },
            },
        ),
        (
            "reflection",
            text("Exit ticket (2 min)", "离场卡（2 分钟）"),
            {
                "type_key": "liveclassroom.short_text",
                "definition": {"prompt": text("Write one command you will remember and what it does.", "写下一条你会记住的命令，以及它的作用。"), "max_length": 240},
            },
        ),
    ]


class Command(BaseCommand):
    help = "Seed public bilingual Bash-for-Linux-beginners example lessons and classrooms."

    def add_arguments(self, parser):
        parser.add_argument("--language", choices=["en", "zh-Hans", "all"], default="all")

    def handle(self, *args, **options):
        languages = [options["language"]] if options["language"] != "all" else ["en", "zh-Hans"]
        owner = self._demo_owner()
        for language in languages:
            demo = self._seed_language(owner, language)
            self.stdout.write(self.style.SUCCESS(f"Seeded {demo.title} ({language})."))

    def _demo_owner(self):
        manager = get_user_model().objects
        owner, created = manager.get_or_create(
            **{get_user_model().USERNAME_FIELD: _DEMO_USERNAME},
            defaults={"is_active": False},
        )
        if not created and owner.is_active:
            owner.is_active = False
            owner.save(update_fields=["is_active"])
        return owner

    def _seed_language(self, owner, language: str) -> DemoLesson:
        course, _ = Course.objects.get_or_create(
            slug=f"liveclassroom-public-demos-{language.lower().replace('-', '')}",
            defaults={
                "title": _TEXT["course"][language],
                "description": _TEXT["course_description"][language],
                "created_by": owner,
            },
        )
        course_changed = []
        for field, value in {
            "title": _TEXT["course"][language],
            "description": _TEXT["course_description"][language],
        }.items():
            if getattr(course, field) != value:
                setattr(course, field, value)
                course_changed.append(field)
        if course_changed:
            course.save(update_fields=[*course_changed, "updated_at"])
        asset = self._asset(owner, language)
        flow, _ = Flow.objects.get_or_create(
            course=course,
            slug=f"{_DEMO_SLUG}-{language.lower().replace('-', '')}",
            defaults={
                "created_by": owner,
                "title": _TEXT["lesson"][language],
                "description": _TEXT["description"][language],
            },
        )
        flow_changed = []
        for field, value in {"title": _TEXT["lesson"][language], "description": _TEXT["description"][language]}.items():
            if getattr(flow, field) != value:
                setattr(flow, field, value)
                flow_changed.append(field)
        if flow_changed:
            flow.save(update_fields=[*flow_changed, "updated_at"])
        definitions = []
        for key, title, content in _lesson_steps(language, asset):
            machine_key = _step_key(language, key)
            step = flow.steps.filter(key=machine_key).select_related("activity_definition").first()
            if step is None:
                # One-time legacy matching is deliberately constrained to the
                # known demo owner, flow, language, and recognized step key.
                legacy_title = f"[bash-demo:{language}:{key}] {title}"
                step = flow.steps.filter(activity_definition__owner=owner, activity_definition__title=legacy_title).first()
                if step is not None:
                    step.key = machine_key
                    step.save(update_fields=["key", "updated_at"])
            if step is None:
                activity = ActivityDefinition.objects.create(
                    owner=owner,
                    course=course,
                    title=title,
                    type_key=content["type_key"],
                    definition=content["definition"],
                    asset=content.get("asset"),
                    status=ActivityDefinition.Status.READY,
                )
                step = FlowStep.objects.create(
                    flow=flow,
                    key=machine_key,
                    position=len(definitions) + 1,
                    activity_definition=activity,
                )
            else:
                activity = step.activity_definition
                changed = []
                if activity.title != title:
                    activity.title = title
                    changed.append("title")
                if activity.asset_id != getattr(content.get("asset"), "id", None):
                    activity.asset = content.get("asset")
                    changed.append("asset")
                if changed:
                    activity.save(update_fields=[*changed, "updated_at"])
                # Revisions keep the reusable definition's old payload intact;
                # existing classroom snapshots deliberately remain untouched.
                if activity.definition != content["definition"]:
                    revise_activity_definition(
                        activity=activity,
                        definition=content["definition"],
                        actor=owner,
                        change_note="Refresh Bash demo content",
                    )
                    activity.refresh_from_db()
            definitions.append(step.activity_definition)
            expected_position = len(definitions)
            if step.position != expected_position:
                step.position = expected_position
                step.save(update_fields=["position", "updated_at"])

        ready = self._session(owner, flow, language, "ready", LiveSession.Status.DRAFT)
        live = self._session(owner, flow, language, "live", LiveSession.Status.LIVE)
        ended = self._session(owner, flow, language, "ended", LiveSession.Status.ENDED)
        self._populate_live_example(live, definitions[1])
        self._populate_finished_example(ended, definitions[5], language)
        demo, _ = DemoLesson.objects.update_or_create(
            slug=_DEMO_SLUG,
            language=language,
            defaults={
                "title": _TEXT["lesson"][language],
                "course": course,
                "flow": flow,
                "ready_session": ready,
                "live_session": live,
                "ended_session": ended,
                "is_public": True,
            },
        )
        return demo

    def _asset(self, owner, language: str) -> ClassroomAsset:
        filename = f"bash-starter-cheatsheet-{language.lower().replace('-', '')}.md"
        body = (
            "# Bash starter cheat sheet\n\n- `pwd`: print the current directory\n- `ls`: list a directory\n- `cd folder`: enter a folder\n- `cat file`: read a text file\n- `echo text`: print text\n"
            if language == "en"
            else "# Bash 入门速查表\n\n- `pwd`：显示当前目录\n- `ls`：列出目录内容\n- `cd 文件夹`：进入文件夹\n- `cat 文件`：读取文本文件\n- `echo 文本`：输出文本\n"
        )
        data = body.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        existing = ClassroomAsset.objects.filter(owner=owner, original_name=filename).first()
        if existing:
            if existing.sha256 != digest:
                existing.content_file.save(filename, ContentFile(data), save=False)
                existing.content_type = "text/markdown; charset=utf-8"
                existing.byte_size = len(data)
                existing.sha256 = digest
                existing.save(update_fields=["content_file", "content_type", "byte_size", "sha256", "updated_at"])
            return existing
        asset = ClassroomAsset(
            owner=owner,
            source=ClassroomAsset.Source.UPLOAD,
            original_name=filename,
            kind=ClassroomAsset.Kind.MARKDOWN,
            content_type="text/markdown; charset=utf-8",
            byte_size=len(data),
            sha256=digest,
        )
        asset.content_file.save(filename, ContentFile(data), save=False)
        asset.save()
        return asset

    def _session(self, owner, flow, language: str, name: str, status: str) -> LiveSession:
        title = _TEXT[name][language]
        session, created = LiveSession.objects.get_or_create(
            teacher=owner,
            title=title,
            defaults={
                "flow": flow,
                "course": flow.course,
                "status": status,
                # Demo sessions are inspectable teacher samples, not public
                # classrooms.  Their retained example answers/chat must never
                # be changed by an uninvited participant.
                "access_mode": LiveSession.AccessMode.AUTHENTICATED,
                "admission_mode": LiveSession.AdmissionMode.ROSTER,
                "chat_enabled": False,
            },
        )
        changed: list[str] = []
        for field, value in {
            "flow": flow,
            "course": flow.course,
            "status": status,
            "access_mode": LiveSession.AccessMode.AUTHENTICATED,
            "admission_mode": LiveSession.AdmissionMode.ROSTER,
            "chat_enabled": False,
        }.items():
            if getattr(session, field) != value:
                setattr(session, field, value)
                changed.append(field)
        if status != LiveSession.Status.DRAFT and session.started_at is None:
            now = timezone.now()
            session.started_at = now
            changed.append("started_at")
            if status == LiveSession.Status.ENDED:
                session.ended_at = now
                changed.append("ended_at")
        if status != LiveSession.Status.ENDED and session.ended_at is not None:
            session.ended_at = None
            changed.append("ended_at")
        if changed:
            session.save(update_fields=[*changed, "updated_at"])
        return session

    def _run(self, session: LiveSession, definition: ActivityDefinition, *, state: str, reviewable: bool) -> LiveActivity:
        existing = session.activities.filter(plan_step__snapshot__activity_definition_id=definition.id).first()
        if existing:
            return existing
        step = session.plan_steps.filter(snapshot__activity_definition_id=definition.id).first()
        snapshot = deepcopy(step.snapshot)
        activity = LiveActivity.objects.create(
            session=session,
            plan_step=step,
            sequence=1,
            kind=definition.type_key.rsplit(".", 1)[-1],
            definition_snapshot=snapshot,
            state=state,
            reviewable=reviewable,
        )
        revision = ActivityRunRevision.objects.create(
            activity=activity,
            revision=1,
            definition_snapshot=snapshot,
            asset=step.asset,
            source_revision=definition.current_revision,
            created_by=session.teacher,
        )
        activity.current_revision = revision
        activity.save(update_fields=["current_revision"])
        for channel in session.channel_states.all():
            channel.current_activity = activity
            channel.current_revision = revision
            channel.show_prompt = True
            channel.show_aggregate = True
            channel.show_own_status = True
            channel.save(
                update_fields=["current_activity", "current_revision", "show_prompt", "show_aggregate", "show_own_status", "updated_at"]
            )
        return activity

    def _submission(self, activity: LiveActivity, participant: Participant, answer: dict) -> None:
        if activity.submissions.filter(participant=participant).exists():
            return
        submission = Submission.objects.create(
            activity=activity,
            participant=participant,
            answer=answer,
        )
        revision = SubmissionRevision.objects.create(
            submission=submission,
            revision=1,
            activity_revision=activity.current_revision,
            answer=answer,
        )
        submission.current_revision = revision
        submission.save(update_fields=["current_revision", "updated_at"])

    def _participant(self, session: LiveSession, name: str) -> Participant:
        participant, _ = Participant.objects.get_or_create(
            session=session,
            guest_id=f"demo-{session.id}-{name.lower().replace(' ', '-')}",
            defaults={"display_name": name, "admission_state": Participant.AdmissionState.ADMITTED},
        )
        return participant

    def _populate_live_example(self, session: LiveSession, definition: ActivityDefinition) -> None:
        activity = self._run(session, definition, state=LiveActivity.State.OPEN, reviewable=False)
        self._submission(activity, self._participant(session, "Alex Example"), {"choice": "some"})
        self._submission(activity, self._participant(session, "Morgan Example"), {"choice": "new"})

    def _populate_finished_example(self, session: LiveSession, definition: ActivityDefinition, language: str) -> None:
        activity = self._run(session, definition, state=LiveActivity.State.CLOSED, reviewable=True)
        transcript = [
            {"command": "pwd", "output": "/home/student", "cwd": "/home/student"},
            {"command": "ls", "output": "README.txt  notes  projects", "cwd": "/home/student"},
            {"command": "cat README.txt", "output": "Welcome!", "cwd": "/home/student"},
            {"command": "cd projects", "output": "", "cwd": "/home/student/projects"},
        ]
        self._submission(
            activity,
            self._participant(session, "Riley Example"),
            {"completed": True, "transcript": transcript},
        )
