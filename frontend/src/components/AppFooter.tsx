export function AppFooter() {
  return (
    <footer className="border-t border-line bg-surface px-4 py-4 text-center text-xs text-ink-muted sm:px-6">
      <div className="mx-auto flex max-w-[88rem] flex-wrap items-center justify-center gap-x-3 gap-y-1.5">
        <span>Developed by <strong className="font-semibold text-ink">Pinaki Sarangi</strong></span>
        <span className="hidden text-line sm:inline" aria-hidden="true">|</span>
        <a className="hover:text-brand-700 hover:underline" href="mailto:pinungr@gmail.com">
          pinungr@gmail.com
        </a>
        <span className="hidden text-line sm:inline" aria-hidden="true">|</span>
        <a className="hover:text-brand-700 hover:underline" href="tel:+917751952860">
          +91 7751952860
        </a>
        <a
          className="font-medium text-brand-700 hover:underline"
          href="https://wa.me/917751952860"
          target="_blank"
          rel="noopener noreferrer"
        >
          WhatsApp
        </a>
      </div>
    </footer>
  )
}
