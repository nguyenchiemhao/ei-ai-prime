// Splits a comma-separated Groups input, trims each group and drops empties.
// Input: text (string). Output: string[]
export const parseGroups = (text: string): string[] =>
  text
    .split(",")
    .map((group) => group.trim())
    .filter((group) => group !== "");
