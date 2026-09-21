{
  description = "Development shell for fusion-plugin-break-marks";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            direnv
            just
            python313
            uv
          ];

          env.UV_PYTHON = "${pkgs.python313}/bin/python";
        };
      });
}
