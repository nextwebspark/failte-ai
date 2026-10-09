// Upstream linked this footer to dograh.com/privacy-policy and
// dograh.com/terms-of-service. Those are the upstream project's legal
// documents, not ours — presenting them under the Fallcha.ai wordmark would tell
// users another company's terms govern this service. They are removed until
// Fallcha.ai has its own policies; restore by putting our URLs in the array
// below and the links render again.
const LEGAL_LINKS: { label: string; href: string }[] = [];

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
