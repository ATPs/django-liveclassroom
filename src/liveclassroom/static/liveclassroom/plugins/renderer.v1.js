export const pluginApiVersion = 1;

export function render(context) {
  // The built-in renderer intentionally delegates to the packaged fallback.
  // External plugins can render their own DOM and return true instead.
  context.fallback();
  return true;
}
