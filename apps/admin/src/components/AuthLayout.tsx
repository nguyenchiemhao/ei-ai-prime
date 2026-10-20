import type { ReactNode } from "react";
import "../pages/auth.css";
import { Logo } from "./Logo";

/** Centered column with the logo, shared by the sign-in, forgot-password and set-password pages. */
export function AuthLayout({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  return (
    <main className="auth-page">
      <div className="auth-column">
        <Logo />
        {children}
        {footer ? <p className="auth-footer">{footer}</p> : null}
      </div>
    </main>
  );
}
