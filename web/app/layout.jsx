import "./globals.css";
import Shell from "@/components/Shell";

export const metadata = {
  title: "Indux · Motor Health",
  description: "Live predictive maintenance for small motors",
};

// Applies the saved theme before first paint, so dark mode never flashes light.
const themeScript = `try{var t=localStorage.getItem("indux-theme");if(t&&t!=="auto")document.documentElement.setAttribute("data-theme",t)}catch(e){}`;

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
