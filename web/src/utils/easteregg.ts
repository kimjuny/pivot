const THINKING_WORDS = [
  "Reticulating",
  "Wizarding",
  "Questing",
  "Boondoggling",
  "Schlepping",
  "Hacking",
  "Finagling",
  "Jiggering",
  "Witching",
  "Conjuring",
  "Enchanting",
  "Voodooing",
  "Clauding",
  "Combobulating",
  "Grokkerating",
  "Noodling",
  "Bitflipping",
  "Bytebonding",
  "Pixelmassaging",
  "Tokenmashing",
  "Syntheosizing",
  "Dillydallying",
  "Loitering",
  "Lingering",
  "Moseying",
  "Fettling",
  "Whirring",
  "Cogitating",
  "Gyroscopicing",
] as const;

/**
 * Returns the rotating easter egg words used by the chat thinking ticker.
 *
 * Why: keeping the words in `src` makes them part of the typed module graph,
 * which avoids Vite's public-asset import restriction and keeps the UI logic
 * self-contained.
 */
export function getThinkingEasterEggWords(): readonly string[] {
  return THINKING_WORDS;
}
