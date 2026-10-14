// Guards the labelling guide against examples that give away the label of a test question (review R2-1).
// The guide is handed to every labeller, so a quoted example that copies, or nearly copies, a test question
// would turn that question into a free label. Translations cannot be detected this way and need a manual read.
import { normalise } from "./text.mjs";

// Quoted strings in the prose of the guide, plus the texts of the example JSON lines in code fences.
export function guideExamples(guide) {
  const examples = [];
  let fence = null;
  for (const line of guide.replace(/\r\n/g, "\n").split("\n")) {
    if (line.startsWith("```")) {
      fence = fence === null ? line.slice(3).trim() : null;
      continue;
    }
    if (fence === null) {
      for (const m of line.matchAll(/"([^"\n]+)"/g)) examples.push(m[1]);
    } else if (line.startsWith("{")) {
      const record = JSON.parse(line);
      examples.push(record.question, ...(record.history ?? []).flatMap((t) => [t.user, t.assistant]));
    }
  }
  return examples;
}

const tokens = (s) => [...new Set(normalise(s).split(" ").filter(Boolean))];

// Returns, for each example of at least `minWords` words, the test question that contains the largest share of
// its words when that share reaches `threshold`.
export function findLeakedExamples(examples, questions, { threshold = 0.8, minWords = 4 } = {}) {
  const sets = questions.map((q) => ({ id: q.id, words: new Set(tokens(q.question)) }));
  const leaks = [];
  for (const example of examples) {
    const words = tokens(example);
    if (words.length < minWords) continue;
    let best = { id: null, overlap: 0 };
    for (const { id, words: qWords } of sets) {
      const overlap = words.filter((w) => qWords.has(w)).length / words.length;
      if (overlap > best.overlap) best = { id, overlap };
    }
    if (best.overlap >= threshold) leaks.push({ example, ...best });
  }
  return leaks;
}
