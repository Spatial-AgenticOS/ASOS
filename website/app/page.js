import Hero from "@/components/Hero";
import AntiHero from "@/components/AntiHero";
import FeatureGrid from "@/components/FeatureGrid";
import InstallTabs from "@/components/InstallTabs";
import ComparisonTable from "@/components/ComparisonTable";
import Community from "@/components/Community";
import Footer from "@/components/Footer";

export default function Home() {
  return (
    <main>
      <Hero />
      <AntiHero />
      <FeatureGrid />
      <InstallTabs />
      <ComparisonTable />
      <Community />
      <Footer />
    </main>
  );
}
