import { configure } from "@testing-library/react";

// Chained async renders (session fetch, workspace fetch, render) can exceed the 1 s default under CPU load.
configure({ asyncUtilTimeout: 5000 });
