## Bugs 

- FQDN portion of the native install doesn't accept user input. It asks for it, but it doesn't actually accept it.
- No final site link ever populates post-install. It should be http://IP:8088
- The CB Cli never installed properly. As a result, no CLI commands work, so the user can't check the status. There should be a fallback note advising the user of the default systemctl command.
- Version # not linked to the VERSION doc. Still showing old 0.3.1 in the install prompt.
