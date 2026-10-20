import Link from "next/link";

export default function CycleNotFound() {
  return (
    <div className="py-24">
      <p className="text-[32px] font-light tracking-[-0.02em]">That decision isn’t in this fund</p>
      <Link href="/cycles" className="mt-3 inline-block text-fund hover:underline">
        See all decisions
      </Link>
    </div>
  );
}
