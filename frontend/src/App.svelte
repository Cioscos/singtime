<script lang="ts">
  import { parseHash, type Route } from "./lib/router";
  import Library from "./screens/Library.svelte";
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
{:else if route.name === "verify"}
  {#key route.id}<Verify id={route.id} />{/key}
{:else}
  <main class="page">
    <p class="muted">Questa schermata non è ancora disponibile.</p>
    <a href="#/library">Torna alla libreria</a>
  </main>
{/if}
