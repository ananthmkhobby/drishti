import { redirect } from "next/navigation";

export default function Home() {
  // Welcome + grade/class + attendance now runs first on every app load —
  // see src/app/welcome/page.tsx — before it hands off to the session
  // dashboard this used to open directly.
  redirect("/welcome");
}
