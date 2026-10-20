import { type createBrowserRouter, RouterProvider } from "react-router";

export function App({ router }: { router: ReturnType<typeof createBrowserRouter> }) {
  return <RouterProvider router={router} />;
}
