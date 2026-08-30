import Link from "next/link";

export default function CycleNotFound() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 py-10 text-center">
      <p className="text-sm font-medium text-foreground">Cycle not found</p>
      <p className="text-sm text-muted-foreground">
        That cycle key is not in the paper ledger.
      </p>
      <Link
        href="/cycles"
        className="font-mono text-xs text-indigo-300 hover:underline"
      >
        Back to cycles
      </Link>
    </div>
  );
}
