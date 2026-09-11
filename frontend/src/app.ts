import { mountTeacherWorkspace } from "./surfaces/workspace/TeacherWorkspace.js";
import { mountAiChat } from "./ai_chat.js";
import { mountBuilder } from "./surfaces/builder/FlowBuilder.js";
import { mountLanguageSwitcher } from "./locales.js";
import { mountStudentSession } from "./surfaces/student/StudentSession.js";
import { mountClassroomDisplay } from "./surfaces/display/ClassroomDisplay.js";
import { mountTeacherConsole } from "./surfaces/teacher/TeacherConsole.js";
import { mountStudentView } from "./surfaces/teacher/StudentView.js";
import { mountDeckWorkspace } from "./surfaces/decks/DeckWorkspace.js";
import { mountAssessmentBuilder } from "./surfaces/assessments/AssessmentBuilder.js";
import { mountStudentAssessment } from "./surfaces/assessments/StudentAssessment.js";
import { mountStudentReview } from "./surfaces/assessments/StudentReview.js";
import { mountLearningWorkspace } from "./surfaces/student/LearningWorkspace.js";
import { mountTeachingCourses } from "./surfaces/workspace/TeachingCourses.js";
import { mountQuestionBankWorkspace } from "./surfaces/questions/QuestionBankWorkspace.js";
import { mountResultsWorkspace } from "./surfaces/assessments/ResultsWorkspace.js";
import { mountAppShell } from "./surfaces/navigation/AppShell.js";
import { mountHomeWorkspace } from "./surfaces/workspace/HomeWorkspace.js";
import { installHistoryRestoration } from "./navigation.js";
import { installBrowseForms } from "./surfaces/navigation/BrowseForms.js";

if (typeof document !== "undefined") {
  installHistoryRestoration();
  installBrowseForms();
  mountAppShell();
  for (const el of document.querySelectorAll<HTMLElement>("[data-home-workspace]")) mountHomeWorkspace(el);
  for (const el of document.querySelectorAll<HTMLElement>("[data-teacher-workspace]")) mountTeacherWorkspace(el);
  for (const el of document.querySelectorAll<HTMLElement>("[data-deck-workspace]")) mountDeckWorkspace(el);
  for (const el of document.querySelectorAll<HTMLElement>("[data-assessment-builder]")) mountAssessmentBuilder(el);
  for (const el of document.querySelectorAll<HTMLElement>("[data-student-assessment]")) mountStudentAssessment(el);
  for (const el of document.querySelectorAll<HTMLElement>("[data-student-review]")) mountStudentReview(el);
  for (const el of document.querySelectorAll<HTMLElement>("[data-learning-workspace]")) mountLearningWorkspace(el);
  for (const el of document.querySelectorAll<HTMLElement>("[data-teaching-courses]")) mountTeachingCourses(el);
  for (const el of document.querySelectorAll<HTMLElement>("[data-question-bank-workspace]")) mountQuestionBankWorkspace(el);
  for (const el of document.querySelectorAll<HTMLElement>("[data-results-workspace]")) mountResultsWorkspace(el);
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
  mountDeckWorkspace,
  mountAssessmentBuilder,
  mountStudentAssessment,
  mountStudentReview,
  mountLearningWorkspace,
  mountTeachingCourses,
  mountQuestionBankWorkspace,
  mountResultsWorkspace,
  mountAppShell,
  mountHomeWorkspace,
};
