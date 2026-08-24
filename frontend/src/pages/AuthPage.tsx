import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { LoaderCircle } from "lucide-react";

import { useAuth } from "@/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useProductName } from "@/config/product-provider";
import { api } from "@/lib/api";

export default function AuthPage({ mode }: { mode: "login" | "register" }) {
  const auth = useAuth();
  const productName = useProductName();
  const navigate = useNavigate();
  const location = useLocation();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [registrationEnabled, setRegistrationEnabled] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.auth
      .config()
      .then((value) => setRegistrationEnabled(value.registration_enabled))
      .catch(() => undefined);
  }, []);

  if (auth.status === "authenticated") {
    return <Navigate to="/data" replace />;
  }

  const requestedPath =
    typeof location.state === "object" && location.state
      ? (location.state as { from?: string }).from
      : undefined;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "register") {
        await auth.register(displayName, email, password);
      } else {
        await auth.login(email, password);
      }
      navigate(requestedPath || "/data", { replace: true });
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not continue.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid h-full overflow-y-auto px-5 py-10 sm:place-items-center">
      <div className="w-full max-w-md">
        <div className="px-7 pt-6">
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            {mode === "register" ? "Create your account" : "Sign in"}
          </h1>
        </div>

        <form className="space-y-5 px-7 py-7" onSubmit={submit}>
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
              {error}
            </div>
          )}

          {mode === "register" && (
            <div className="space-y-2">
              <Label htmlFor="display-name">Name</Label>
              <Input
                id="display-name"
                autoComplete="name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                required
                autoFocus
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              autoFocus={mode === "login"}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete={
                mode === "register" ? "new-password" : "current-password"
              }
              minLength={10}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            {mode === "register" && (
              <p className="text-xs text-muted-foreground">
                Use at least 10 characters.
              </p>
            )}
          </div>

          <Button
            type="submit"
            className="w-full justify-center"
            disabled={
              submitting || (mode === "register" && !registrationEnabled)
            }
          >
            {submitting && <LoaderCircle className="size-4 animate-spin" />}
            {mode === "register" ? "Create account" : "Sign in"}
          </Button>

          <p className="text-center text-sm text-muted-foreground">
            {mode === "register" ? "Already have an account? " : "New here? "}
            {mode === "register" ? (
              <Link
                className="font-medium text-blue-700 hover:underline dark:text-blue-300"
                to="/login"
              >
                Sign in
              </Link>
            ) : registrationEnabled ? (
              <Link
                className="font-medium text-blue-700 hover:underline dark:text-blue-300"
                to="/register"
              >
                Create an account
              </Link>
            ) : (
              <span>Registration is disabled.</span>
            )}
          </p>
        </form>
      </div>
    </div>
  );
}
