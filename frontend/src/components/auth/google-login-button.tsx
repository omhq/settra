type GoogleLoginButtonProps = {
  disabled?: boolean;
  onClick: () => void;
};

function GoogleIcon() {
  return (
    <svg
      aria-hidden="true"
      className="block size-5"
      focusable="false"
      viewBox="0 0 48 48"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

export function GoogleLoginButton({
  disabled = false,
  onClick,
}: GoogleLoginButtonProps) {
  return (
    <button
      type="button"
      className="group relative grid h-10 w-full grid-cols-[40px_minmax(0,1fr)_40px] items-center overflow-hidden rounded-full border border-transparent bg-[#f2f2f2] p-0 text-center text-sm font-medium tracking-[0.25px] whitespace-nowrap text-[#1f1f1f] transition-[background-color,border-color,box-shadow] duration-200 [font-family:Roboto,Arial,sans-serif] enabled:cursor-pointer enabled:hover:shadow-[0_1px_2px_0_rgba(60,64,67,0.30),0_1px_3px_1px_rgba(60,64,67,0.15)] focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-[#4285f4]/40 disabled:pointer-events-none disabled:cursor-default disabled:opacity-[0.38] dark:border-[#8e918f] dark:bg-[#131314] dark:text-[#e3e3e3]"
      disabled={disabled}
      onClick={onClick}
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[#001d35] opacity-0 transition-opacity duration-200 group-hover:opacity-[0.08] group-active:opacity-[0.12] group-focus-visible:opacity-[0.12] dark:bg-white"
      />
      <span className="relative grid size-10 place-items-center">
        <GoogleIcon />
      </span>
      <span className="relative truncate px-2">Continue with Google</span>
      <span aria-hidden="true" className="size-10" />
    </button>
  );
}
