export const pluginApiVersion = 1;

export function createEditor(context) {
  return {
    typeKey: context.typeKey,
    render: context.fallback,
  };
}
