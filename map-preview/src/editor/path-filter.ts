/**
 * Tiny pure helper for case-insensitive substring filtering of output file
 * paths against a search query. Kept free of DOM/API concerns so it can be
 * unit-tested in isolation.
 */

/**
 * Whether a full relative path matches a search query.
 * An empty/whitespace query matches everything; otherwise a case-insensitive
 * substring match is performed against the entire path.
 */
export function pathMatchesQuery(path: string, query: string): boolean {
  const q = query.trim();
  if (q === "") return true;
  return path.toLowerCase().includes(q.toLowerCase());
}
