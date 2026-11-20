export function download(name: string, text: string | Blob, type: string) {
  const u = URL.createObjectURL(text instanceof Blob ? text : new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = u;
  a.download = name;
  a.click();
  URL.revokeObjectURL(u);
}
