import { BRAND } from "@/config/brand";

// Our own policies (upstream linked Dograh's, which don't govern this service).
const LEGAL_LINKS: { label: string; href: string }[] = [
  { label: "Terms of Service", href: BRAND.termsUrl },
  { label: "Privacy Policy", href: BRAND.privacyUrl },
];

export default function Footer() {
  if (LEGAL_LINKS.length === 0) {
    return null;
  }

  return (
    <footer className="fixed bottom-0 left-0 right-0 bg-background border-t border-border py-4 px-6">
      <div className="flex justify-center items-center gap-6 text-sm text-muted-foreground">
        {LEGAL_LINKS.map((link, index) => (
          <span key={link.href} className="flex items-center gap-6">
            {index > 0 && <span className="text-border">|</span>}
            <a
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-foreground transition-colors"
            >
              {link.label}
            </a>
          </span>
        ))}
      </div>
    </footer>
  );
}
