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

function initLiveClassroom() {
  const safe = (name: string, fn: () => void) => {
    try {
      fn();
    } catch (err) {
      console.error(`[LiveClassroom] Failed to mount ${name}:`, err);
    }
  };

  safe("HistoryRestoration", () => installHistoryRestoration());
  safe("BrowseForms", () => installBrowseForms());
  safe("AppShell", () => mountAppShell());

  for (const el of document.querySelectorAll<HTMLElement>("[data-home-workspace]")) safe("HomeWorkspace", () => mountHomeWorkspace(el));
  for (const el of document.querySelectorAll<HTMLElement>("[data-teacher-workspace]")) safe("TeacherWorkspace", () => mountTeacherWorkspace(el));
  for (const el of document.querySelectorAll<HTMLElement>("[data-deck-workspace]")) safe("DeckWorkspace", () => mountDeckWorkspace(el));
  for (const el of document.querySelectorAll<HTMLElement>("[data-assessment-builder]")) safe("AssessmentBuilder", () => mountAssessmentBuilder(el));
  for (const el of document.querySelectorAll<HTMLElement>("[data-student-assessment]")) safe("StudentAssessment", () => mountStudentAssessment(el));
  for (const el of document.querySelectorAll<HTMLElement>("[data-student-review]")) safe("StudentReview", () => mountStudentReview(el));
  for (const el of document.querySelectorAll<HTMLElement>("[data-learning-workspace]")) safe("LearningWorkspace", () => mountLearningWorkspace(el));
  for (const el of document.querySelectorAll<HTMLElement>("[data-teaching-courses]")) safe("TeachingCourses", () => mountTeachingCourses(el));
  for (const el of document.querySelectorAll<HTMLElement>("[data-question-bank-workspace]")) safe("QuestionBankWorkspace", () => mountQuestionBankWorkspace(el));
  for (const el of document.querySelectorAll<HTMLElement>("[data-results-workspace]")) safe("ResultsWorkspace", () => mountResultsWorkspace(el));

  for (const element of document.querySelectorAll<HTMLElement>("[data-liveclassroom-app]")) {
    const audience = element.dataset.audience;
    if (audience === "student" && element.dataset.stateUrl) safe("StudentSession", () => mountStudentSession(element));
    else if (audience === "display" && element.dataset.stateUrl) safe("ClassroomDisplay", () => mountClassroomDisplay(element));
    else if (audience === "teacher" && element.dataset.stateUrl) safe("TeacherConsole", () => mountTeacherConsole(element));
  }

  for (const element of document.querySelectorAll<HTMLElement>("[data-liveclassroom-builder]")) safe("Builder", () => void mountBuilder(element));
  for (const element of document.querySelectorAll<HTMLElement>("[data-liveclassroom-ai-chat]")) safe("AiChat", () => void mountAiChat(element));
  for (const element of document.querySelectorAll<HTMLElement>("[data-student-view]")) safe("StudentView", () => mountStudentView(element));
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLiveClassroom);
  } else {
    initLiveClassroom();
  }
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
