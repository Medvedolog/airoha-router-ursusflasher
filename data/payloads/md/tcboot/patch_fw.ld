PROVIDE(run_command = 0x81e21140);
PROVIDE(install_script = 0x81e8b8f7);
PROVIDE(post_script = 0x81e8de8f);
PROVIDE(epilogue = 0x81e77fbc);
SECTIONS { . = 0x81e77f0c; .text : { *(.text*) } }
