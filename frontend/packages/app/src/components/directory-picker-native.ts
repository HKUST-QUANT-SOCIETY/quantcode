export function openNativeDirectoryPicker(
  open: () => Promise<string | string[] | null>,
  onSelect: (result: string | string[] | null) => void,
) {
  return Promise.resolve()
    .then(open)
    .then(onSelect, () => onSelect(null))
}
