export const pluginApiVersion = 1;

const COMMANDS = ["pwd", "ls", "cd", "cat", "echo", "help", "clear", "reset"];
const COMMAND_SET = new Set(COMMANDS);
const MAX_TRANSCRIPT_ENTRIES = 100;
const MAX_COMMAND_LENGTH = 240;

function text(value, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function contentFor(activity) {
  const definition = activity && activity.definition && typeof activity.definition === "object"
    ? activity.definition
    : {};
  return definition.content && typeof definition.content === "object" && !Array.isArray(definition.content)
    ? definition.content
    : definition;
}

function pathFor(value, cwd) {
  const source = text(value, ".");
  const parts = (source.startsWith("/") ? source : `${cwd}/${source}`).split("/");
  const result = [];
  for (const part of parts) {
    if (!part || part === ".") continue;
    if (part === "..") result.pop();
    else result.push(part);
  }
  return `/${result.join("/")}` || "/";
}

function directoriesFor(files) {
  const directories = new Set(["/"]);
  for (const path of Object.keys(files)) {
    const parts = path.split("/").filter(Boolean);
    let current = "";
    for (const part of parts.slice(0, -1)) {
      current += `/${part}`;
      directories.add(current);
    }
  }
  return directories;
}

function parseCommand(line) {
  const command = line.trim();
  if (!command || command.length > MAX_COMMAND_LENGTH || /[;|&<>$`\n\r]/.test(command)) {
    return { name: "", args: [], error: "Only one simple command is allowed per line." };
  }
  const parts = command.split(/\s+/);
  const name = parts.shift() || "";
  if (!COMMAND_SET.has(name)) return { name, args: parts, error: `${name}: command not found` };
  return { name, args: parts, error: "" };
}

function listDirectory(path, files, directories) {
  if (files[path] !== undefined) return { output: `ls: ${path}: Not a directory` };
  if (!directories.has(path)) return { output: `ls: ${path}: No such file or directory` };
  const prefix = path === "/" ? "/" : `${path}/`;
  const names = new Set();
  for (const candidate of [...Object.keys(files), ...directories]) {
    if (!candidate.startsWith(prefix) || candidate === path) continue;
    const remainder = candidate.slice(prefix.length);
    if (remainder && !remainder.includes("/")) names.add(remainder);
  }
  return { output: [...names].sort().join("  ") };
}

function runCommand(parsed, cwd, files, directories, initialDirectory) {
  const { name, args } = parsed;
  if (parsed.error) return { cwd, output: parsed.error };
  if (["pwd", "help", "clear", "reset"].includes(name) && args.length) {
    return { cwd, output: `${name}: too many arguments` };
  }
  if (["ls", "cd"].includes(name) && args.length > 1) {
    return { cwd, output: `${name}: too many arguments` };
  }
  if (name === "pwd") return { cwd, output: cwd };
  if (name === "help") return { cwd, output: `Available commands: ${COMMANDS.join(", ")}` };
  if (name === "echo") return { cwd, output: args.join(" ") };
  if (name === "clear") return { cwd, output: "", clear: true };
  if (name === "reset") return { cwd: initialDirectory, output: `Reset to ${initialDirectory}.` };
  if (name === "ls") return { cwd, ...listDirectory(pathFor(args[0] || cwd, cwd), files, directories) };
  if (name === "cd") {
    const target = pathFor(args[0] || "/", cwd);
    if (files[target] !== undefined) return { cwd, output: `cd: ${target}: Not a directory` };
    if (!directories.has(target)) return { cwd, output: `cd: ${target}: No such file or directory` };
    return { cwd: target, output: "" };
  }
  if (name === "cat") {
    if (!args.length) return { cwd, output: "cat: missing operand" };
    const output = [];
    for (const argument of args) {
      const target = pathFor(argument, cwd);
      if (files[target] === undefined) {
        output.push(`${target}: No such file or directory`);
      } else {
        output.push(files[target]);
      }
    }
    return { cwd, output: output.join("\n") };
  }
  return { cwd, output: `${name}: command not found` };
}

function appendEntry(entries, entry, limit = MAX_TRANSCRIPT_ENTRIES) {
  if (entries.length >= limit) return entries;
  return [...entries, entry];
}

function renderTranscript(output, entries) {
  output.replaceChildren();
  for (const entry of entries) {
    const line = document.createElement("div");
    const command = document.createElement("span");
    command.textContent = `${entry.cwd}$ ${entry.command}`;
    line.append(command);
    if (entry.output) {
      const result = document.createElement("pre");
      result.textContent = entry.output;
      line.append(result);
    }
    output.append(line);
  }
  output.scrollTop = output.scrollHeight;
}

function completedAnswer(state) {
  const submission = state && state.my_submission;
  const answer = submission && submission.answer;
  if (!answer || submission.is_stale || answer.completed !== true || !Array.isArray(answer.transcript)) return null;
  return answer;
}

function draftKey(context, activity) {
  const participant = context.state && context.state.participant;
  const identity = participant && participant.id ? participant.id : "preview";
  return `liveclassroom.bash.v1:${identity}:${activity.id || "activity"}:${activity.revision || "revision"}`;
}

function loadDraft(key, directories, initialDirectory, limit) {
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(key) || "null");
    if (!saved || !Array.isArray(saved.transcript) || !Array.isArray(saved.visibleTranscript)) return null;
    const cwd = text(saved.cwd, initialDirectory);
    if (!directories.has(cwd)) return null;
    return {
      cwd,
      transcript: saved.transcript.slice(0, limit),
      visibleTranscript: saved.visibleTranscript.slice(0, limit),
    };
  } catch {
    return null;
  }
}

function saveDraft(key, draft) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // Storage can be unavailable in a privacy-restricted tab; the terminal
    // remains usable and server completion is still authoritative.
  }
}

function requirementsFor(content, transcript, cwd) {
  const completion = content.completion && typeof content.completion === "object" ? content.completion : {};
  const required = Array.isArray(completion.required_commands) ? completion.required_commands : [];
  const seen = new Set(transcript.map((entry) => parseCommand(text(entry.command)).name));
  return {
    required,
    steps: required.map((command) => ({ command, done: seen.has(command) })),
    directory: text(completion.required_directory),
    directoryDone: !text(completion.required_directory) || cwd === completion.required_directory,
  };
}

export function render(context) {
  const activity = context.activity || {};
  const content = contentFor(activity);
  const files = content.filesystem && typeof content.filesystem === "object" ? content.filesystem : {};
  const directories = directoriesFor(files);
  const configuredLimit = Number(content.max_transcript_entries);
  const transcriptLimit = Number.isInteger(configuredLimit) && configuredLimit > 0
    ? Math.min(configuredLimit, MAX_TRANSCRIPT_ENTRIES)
    : MAX_TRANSCRIPT_ENTRIES;
  const initialDirectory = directories.has(text(content.initial_directory, "/"))
    ? text(content.initial_directory, "/")
    : "/";
  const previous = completedAnswer(context.state);
  const chinese = text(context.locale).startsWith("zh");
  const labels = chinese ? {
    run: "运行", completed: "已完成", complete: "完成练习", saving: "正在保存…",
    saved: "已完成并保存。", failed: "无法保存完成记录。", limit: "已达到记录上限。", resetAttempt: "重新开始练习", tryCommands: "试用命令",
    directory: "当前目录：", command: "命令", fixed: "学生只会在固定的浏览器虚拟文件系统中练习。",
  } : {
    run: "Run", completed: "Completed", complete: "Complete activity", saving: "Saving…",
    saved: "Completed and saved.", failed: "Could not save completion.", limit: "Transcript limit reached.", resetAttempt: "Reset practice", tryCommands: "Try commands",
    directory: "Working directory: ", command: "Command", fixed: "Students interact with a fixed browser virtual filesystem.",
  };
  const key = draftKey(context, activity);
  const draft = previous ? null : loadDraft(key, directories, initialDirectory, transcriptLimit);
  const history = previous ? previous.transcript.slice(0, transcriptLimit) : (draft ? draft.transcript : []);
  let cwd = draft ? draft.cwd : (history.length ? history[history.length - 1].cwd : initialDirectory);
  if (!directories.has(cwd)) cwd = initialDirectory;
  let transcript = history;
  let visibleTranscript = draft ? draft.visibleTranscript : history;
  let currentContext = context;
  let saved = Boolean(previous);
  let saving = false;
  let limitReached = !saved && transcript.length >= transcriptLimit;

  const heading = document.createElement("h3");
  heading.textContent = text(activity.definition && activity.definition.title, "Bash simulator");
  context.container.append(heading);
  const prompt = document.createElement("p");
  prompt.textContent = text(content.prompt);
  context.container.append(prompt);

  if (context.readOnly && context.audience === "student") {
    const readOnlyNote = document.createElement("p");
    readOnlyNote.textContent = chinese
      ? "这是只读学生预览。以测试学生身份打开后才能运行命令和保存练习。"
      : "This is a read-only student preview. Open it as a test student to run commands and save practice.";
    context.container.append(readOnlyNote);
  }

  if (context.audience !== "student") {
    const examples = document.createElement("ul");
    const required = requirementsFor(content, [], initialDirectory).required;
    for (const command of required) {
      const item = document.createElement("li");
      item.textContent = command;
      examples.append(item);
    }
    if (required.length) context.container.append(examples);
    if (context.audience === "teacher") {
      const note = document.createElement("p");
      note.textContent = chinese ? "可私下试用命令；这不会保存学生作答。" : "Try commands privately; this never saves a student response.";
      const tryButton = document.createElement("button");
      tryButton.type = "button";
      tryButton.textContent = labels.tryCommands;
      tryButton.addEventListener("click", () => {
        context.container.replaceChildren();
        render({ ...context, audience: "student", readOnly: false, submit: undefined });
      });
      context.container.append(note, tryButton);
    }
    return true;
  }

  const terminal = document.createElement("section");
  terminal.className = "lc-bash-simulator";
  const directory = document.createElement("p");
  directory.className = "lc-bash-simulator-directory";
  terminal.append(directory);
  const output = document.createElement("div");
  output.className = "lc-bash-simulator-output";
  output.setAttribute("aria-live", "polite");
  terminal.append(output);
  const form = document.createElement("form");
  form.className = "lc-bash-simulator-form";
  const input = document.createElement("input");
  input.type = "text";
  input.autocomplete = "off";
  input.maxLength = MAX_COMMAND_LENGTH;
  input.id = `lc-bash-command-${activity.id || "activity"}-${activity.revision || "revision"}`;
  const inputLabel = document.createElement("label");
  inputLabel.htmlFor = input.id;
  inputLabel.textContent = labels.command;
  input.placeholder = chinese ? "输入 pwd 后按 Enter" : "Type pwd and press Enter";
  const run = document.createElement("button");
  run.type = "submit";
  run.textContent = labels.run;
  form.append(inputLabel, input, run);
  terminal.append(form);
  const actions = document.createElement("div");
  const complete = document.createElement("button");
  complete.type = "button";
  complete.textContent = previous ? labels.completed : labels.complete;
  const status = document.createElement("span");
  status.setAttribute("role", "status");
  actions.append(complete, status);
  terminal.append(actions);
  const checklist = document.createElement("ol");
  checklist.className = "lc-bash-simulator-checklist";
  terminal.append(checklist);
  context.container.append(terminal);
  renderTranscript(output, visibleTranscript);

  const refreshChecklist = () => {
    const requirements = requirementsFor(content, transcript, cwd);
    checklist.replaceChildren();
    for (const step of requirements.steps) {
      const item = document.createElement("li");
      item.textContent = `${step.done ? "✓" : "○"} ${step.command}`;
      checklist.append(item);
    }
    if (requirements.directory) {
      const item = document.createElement("li");
      item.textContent = `${requirements.directoryDone ? "✓" : "○"} ${requirements.directory}`;
      checklist.append(item);
    }
    const writable = !currentContext.readOnly && Boolean(currentContext.submit) && !saved && !saving;
    input.disabled = !writable || limitReached;
    run.disabled = !writable || limitReached;
    complete.disabled = !writable || !requirements.steps.every((step) => step.done) || !requirements.directoryDone;
    if (!saved && complete.disabled && requirements.required.length && !limitReached && !saving) {
      status.textContent = chinese ? "完成清单中的步骤后可提交。" : "Complete every listed step before submitting.";
    }
    directory.textContent = `${labels.directory}${cwd}`;
  };
  refreshChecklist();

  const resetAttempt = () => {
    cwd = initialDirectory;
    transcript = [];
    visibleTranscript = [];
    limitReached = false;
    saveDraft(key, { cwd, transcript, visibleTranscript });
    renderTranscript(output, visibleTranscript);
    status.textContent = "";
    refreshChecklist();
    if (!input.disabled) input.focus();
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (input.disabled) return;
    const command = input.value.trim();
    if (!command) return;
    const before = cwd;
    const parsed = parseCommand(command);
    const result = runCommand(parsed, cwd, files, directories, initialDirectory);
    cwd = result.cwd;
    const entry = { command, output: text(result.output), cwd };
    transcript = appendEntry(transcript, entry, transcriptLimit);
    visibleTranscript = result.clear ? [] : appendEntry(visibleTranscript, entry, transcriptLimit);
    renderTranscript(output, visibleTranscript);
    saveDraft(key, { cwd, transcript, visibleTranscript });
    refreshChecklist();
    input.value = "";
    input.focus();
    if (transcript.length >= transcriptLimit) {
      limitReached = true;
      status.replaceChildren(document.createTextNode(labels.limit), document.createTextNode(" "));
      const reset = document.createElement("button");
      reset.type = "button";
      reset.textContent = labels.resetAttempt;
      reset.addEventListener("click", resetAttempt);
      status.append(reset);
      refreshChecklist();
    }
    if (before !== cwd && !result.output) status.textContent = `${labels.directory}${cwd}`;
  });

  complete.addEventListener("click", () => {
    if (!currentContext.submit || saved || saving || !transcript.length || complete.disabled) return;
    saving = true;
    refreshChecklist();
    status.textContent = labels.saving;
    void currentContext.submit({ completed: true, transcript }).then(() => {
      saving = false;
      saved = true;
      status.textContent = labels.saved;
      try { window.sessionStorage.removeItem(key); } catch {}
      refreshChecklist();
    }).catch((error) => {
      saving = false;
      status.textContent = error instanceof Error ? error.message : labels.failed;
      refreshChecklist();
    });
  });
  return {
    update(nextContext) {
      currentContext = nextContext;
      saved = saved || Boolean(completedAnswer(nextContext.state));
      refreshChecklist();
    },
  };
}
