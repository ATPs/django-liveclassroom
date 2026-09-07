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
  if (name === "ls") return listDirectory(pathFor(args[0] || cwd, cwd), files, directories);
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
    saved: "已完成并保存。", failed: "无法保存完成记录。", limit: "已达到记录上限。",
    directory: "当前目录：", fixed: "学生只会在固定的浏览器虚拟文件系统中练习。",
  } : {
    run: "Run", completed: "Completed", complete: "Complete activity", saving: "Saving…",
    saved: "Completed and saved.", failed: "Could not save completion.", limit: "Transcript limit reached.",
    directory: "Working directory: ", fixed: "Students interact with a fixed browser virtual filesystem.",
  };
  const history = previous ? previous.transcript.slice(0, transcriptLimit) : [];
  let cwd = history.length ? history[history.length - 1].cwd : initialDirectory;
  if (!directories.has(cwd)) cwd = initialDirectory;
  let transcript = history;
  let visibleTranscript = history;

  const heading = document.createElement("h3");
  heading.textContent = text(activity.definition && activity.definition.title, "Bash simulator");
  context.container.append(heading);
  const prompt = document.createElement("p");
  prompt.textContent = text(content.prompt);
  context.container.append(prompt);

  if (context.audience !== "student") {
    const note = document.createElement("p");
    note.textContent = labels.fixed;
    context.container.append(note);
    return true;
  }

  const terminal = document.createElement("section");
  terminal.className = "lc-bash-simulator";
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
  input.setAttribute("aria-label", "Bash command");
  const run = document.createElement("button");
  run.type = "submit";
  run.textContent = labels.run;
  form.append(input, run);
  terminal.append(form);
  const actions = document.createElement("div");
  const complete = document.createElement("button");
  complete.type = "button";
  complete.textContent = previous ? labels.completed : labels.complete;
  const status = document.createElement("span");
  status.setAttribute("role", "status");
  actions.append(complete, status);
  terminal.append(actions);
  context.container.append(terminal);
  renderTranscript(output, visibleTranscript);

  const setDisabled = (value) => {
    input.disabled = value;
    run.disabled = value;
    complete.disabled = value || !context.submit;
  };
  setDisabled(Boolean(previous));

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
    input.value = "";
    if (transcript.length >= transcriptLimit) status.textContent = labels.limit;
    if (before !== cwd && !result.output) status.textContent = `${labels.directory}${cwd}`;
  });

  complete.addEventListener("click", () => {
    if (!context.submit || previous || !transcript.length) return;
    complete.disabled = true;
    status.textContent = labels.saving;
    void context.submit({ completed: true, transcript }).then(() => {
      status.textContent = labels.saved;
      input.disabled = true;
      run.disabled = true;
    }).catch((error) => {
      complete.disabled = false;
      status.textContent = error instanceof Error ? error.message : labels.failed;
    });
  });
  return true;
}
