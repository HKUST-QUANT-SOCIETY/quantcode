import { DIFFS_TAG_NAME } from "@pierre/diffs"

/**
 * TypeScript declaration for the <diffs-container> custom element.
 *
 * Keep this declaration as a regular file instead of a symbolic link so the
 * application can be type-checked from Windows checkouts where Git symlink
 * support is unavailable.
 */
declare module "solid-js" {
  namespace JSX {
    interface IntrinsicElements {
      [DIFFS_TAG_NAME]: HTMLAttributes<HTMLElement>
    }
  }
}

export {}
