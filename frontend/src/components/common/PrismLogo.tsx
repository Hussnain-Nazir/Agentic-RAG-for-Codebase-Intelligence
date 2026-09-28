/**
 * Brand mark. Renders the placeholder /public/logo.webp asset.
 * Replacing that file with the final PRISM logo requires no changes here.
 */
export function PrismLogo({ size = 24, className = "" }: { size?: number; className?: string }) {
  return (
    <img
      src="/logo.webp"
      alt=""
      role="presentation"
      width={size}
      height={size}
      className={className}
      draggable={false}
    />
  );
}
