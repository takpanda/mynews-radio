export function sanitizeFilename(name: string): string {
  return name.replace(/[\\/:*?"<>|]/g, '_').replace(/\0/g, '').replace(/\s+/g, ' ').trim().slice(0, 80) || 'untitled'
}
