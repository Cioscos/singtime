<script lang="ts">
  import { parseHash, type Route } from "./lib/router";
  import Calibration from "./screens/Calibration.svelte";
  import EditSong from "./screens/EditSong.svelte";
  import Game from "./screens/Game.svelte";
  import Library from "./screens/Library.svelte";
  import Result from "./screens/Result.svelte";
  import Settings from "./screens/Settings.svelte";
  import Verify from "./screens/Verify.svelte";

  let route = $state<Route>(parseHash(location.hash));

  $effect(() => {
    const onHashChange = () => (route = parseHash(location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  });
</script>

{#if route.name === "library"}
  <Library />
{:else if route.name === "game"}
  {#key route.id}<Game id={route.id} />{/key}
{:else if route.name === "edit"}
  {#key route.id}<EditSong id={route.id} />{/key}
{:else if route.name === "result"}
  {#key route.id}<Result id={route.id} />{/key}
{:else if route.name === "calibration"}
  <Calibration />
{:else if route.name === "settings"}
  <Settings />
{:else if route.name === "verify"}
  {#key route.id}<Verify id={route.id} />{/key}
{/if}
