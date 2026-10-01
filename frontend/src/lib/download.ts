/**
 * Hand a generated file to the user.
 *
 * Two hosts, two mechanisms. Served normally - dev server, a real deployment,
 * a local `file://` copy - a blob URL and a synthetic click is the whole job.
 * Published as a claude.ai Artifact, the page runs in a sandboxed frame where
 * that click is quietly ignored: no error, no file, nothing. The viewer clicks
 * Export and believes it worked.
 *
 * So when the Artifact runtime is present we go through it, which shows the
 * viewer a confirmation and can be declined. Everywhere else the ordinary path
 * is unchanged.
 */

declare global {
  interface Window {
    claude?: {
      use?: (name: string) => Promise<{
        save?: (request: { filename: string; data: string | Blob }) => Promise<unknown>;
      } | null>;
    };
  }
}

export type DownloadResult = 'saved' | 'declined' | 'unavailable';

function saveViaAnchor(filename: string, contents: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([contents], { type: mime }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function saveFile(
  filename: string,
  contents: string,
  mime: string,
): Promise<DownloadResult> {
  const use = typeof window !== 'undefined' ? window.claude?.use : undefined;
  if (!use) {
    saveViaAnchor(filename, contents, mime);
    return 'saved';
  }

  // Inside the Artifact frame. `use` resolves null when this view cannot run
  // the capability, and `save` rejects when the viewer declines - neither is
  // an error worth throwing, but neither is a successful save either.
  try {
    const downloads = await use('downloads');
    if (!downloads?.save) return 'unavailable';
    await downloads.save({ filename, data: contents });
    return 'saved';
  } catch {
    return 'declined';
  }
}
