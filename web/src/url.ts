/** Public application URL, including the Vite deployment prefix. */
export function appUrl(path: string): string {
  return `${import.meta.env.BASE_URL.replace(/\/$/, '')}${path}`
}
