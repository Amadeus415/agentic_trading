import Link from "next/link";

export default function PositionNotFound() {
  return (
    <div className="py-24">
      <p className="text-[32px] font-light tracking-[-0.02em]">This fund never traded that contract</p>
      <Link href="/" className="mt-3 inline-block text-fund hover:underline">
        Back to the overview
      </Link>
    </div>
  );
}
