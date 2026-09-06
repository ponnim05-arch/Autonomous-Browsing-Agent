// The import must match what the component file is actually called. In the 21st sandbox
// it is saved as component.tsx, so this resolves to "@/components/ui/component".
// If you rename the file to handwriting-text.tsx, change this to match.
import { HandwritingText } from "@/components/ui/handwriting-text";

export default function Demo() {
  return (
    <div className="flex min-h-[360px] w-full flex-col items-center justify-center gap-10 px-6">
      <h1 className="max-w-2xl text-center text-4xl font-bold leading-tight tracking-tight text-zinc-900 sm:text-5xl dark:text-zinc-50">
        Know where the crowd
        <br />
        is going to break
        <br />
        <HandwritingText
          words={["live.", "predictive.", "measurable.", "on every phone."]}
          className="text-emerald-700 dark:text-emerald-400"
          height="1.15em"
        />
      </h1>

      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Each word is traced letter by letter, then inked in.
      </p>
    </div>
  );
}
