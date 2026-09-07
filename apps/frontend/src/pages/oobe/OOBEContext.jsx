import { createContext, useContext } from 'react';

/**
 * Everything the first-run wizard's steps read, in one context.
 *
 * The steps were seven inline JSX blocks inside a 2,215-line
 * `OOBEWizardPage`, and they share a great deal of state: the account step
 * alone touches around fifty of the page's values, between the credential
 * fields, the OAuth bootstrap, the avatar and the setup token. Extracting them
 * as components with props would have replaced one long file with a fifty-prop
 * signature, which is not an improvement.
 *
 * A context is the right shape for a wizard: the page owns the state and the
 * transitions, each step reads the slice it needs, and adding a field to a step
 * does not mean editing a prop list in two files. Nothing re-renders that did
 * not re-render before — the steps used to be part of the page's own render.
 */
const OOBEContext = createContext(null);

export function useOOBE() {
  const value = useContext(OOBEContext);
  if (value === null) {
    throw new Error('useOOBE must be used inside the OOBE wizard');
  }
  return value;
}

export default OOBEContext;
