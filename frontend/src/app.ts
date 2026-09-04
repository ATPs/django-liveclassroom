import { mountAiChat } from "./ai_chat.js";
import { mountBuilder } from "./builder.js";
import { mountLanguageSwitcher } from "./locales.js";
import { mountStudentSession } from "./surfaces/student/StudentSession.js";
import { mountClassroomDisplay } from "./surfaces/display/ClassroomDisplay.js";
import { mountTeacherConsole } from "./surfaces/teacher/TeacherConsole.js";
import { mountStudentView } from "./surfaces/teacher/StudentView.js";

if (typeof document !== "undefined") {
  for (const element of document.querySelectorAll<HTMLElement>("[data-liveclassroom-app]")) {
    const audience = element.dataset.audience;
    if (audience === "student" && element.dataset.stateUrl) mountStudentSession(element);
    else if (audience === "display" && element.dataset.stateUrl) mountClassroomDisplay(element);
    else if (audience === "teacher" && element.dataset.stateUrl) mountTeacherConsole(element);
  }
  for (const element of document.querySelectorAll<HTMLElement>("[data-liveclassroom-builder]")) void mountBuilder(element);
  for (const element of document.querySelectorAll<HTMLElement>("[data-liveclassroom-ai-chat]")) void mountAiChat(element);
  for (const element of document.querySelectorAll<HTMLElement>("[data-student-view]")) mountStudentView(element);
}

export {
  mountLanguageSwitcher,
  mountStudentSession,
  mountClassroomDisplay,
  mountTeacherConsole,
  mountBuilder,
  mountAiChat,
  mountStudentView,
};
