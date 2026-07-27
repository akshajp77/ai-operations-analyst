import { redirect } from "next/navigation";

/**
 * The `/` route.
 *
 * Uploading a dataset is the only way into the product — every other view
 * needs a dataset to exist first — so the root sends people straight there
 * rather than showing a landing page with one link on it. Replace this with a
 * real home page once there is something to show a returning user, such as a
 * list of their existing datasets.
 */
export default function Home() {
  redirect("/upload");
}
