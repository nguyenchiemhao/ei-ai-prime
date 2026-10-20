import { useNavigate } from "react-router";
import { PATHS } from "../paths";
import { useSession } from "./SessionProvider";

/** Ends the session on the server, then goes to the sign-in page. */
export function useSignOut(): () => Promise<void> {
  const { signOut } = useSession();
  const navigate = useNavigate();
  return async () => {
    await signOut();
    void navigate(PATHS.signIn, { replace: true });
  };
}
