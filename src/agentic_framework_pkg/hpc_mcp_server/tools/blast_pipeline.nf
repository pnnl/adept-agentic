#!/usr/bin/env nextflow
nextflow.enable.dsl=2

// Define parameters that will be passed from the Python tool
params.query_file = false // Path to the query FASTA file
params.db_name = "nr"     // Name of the BLAST database
params.blast_program = "blastp" // BLAST program (e.g., blastp, blastn)
params.outdir = "./results"     // Directory to store results
params.output_format = "6"      // BLAST output format code

// Log parameters for debugging within Nextflow's execution log
log.info """
         -----------------------------------------
         N E X T F L O W   B L A S T   P I P E L I N E
         -----------------------------------------
         Query file      : ${params.query_file}
         Database        : ${params.db_name}
         BLAST program   : ${params.blast_program}
         Output directory: ${params.outdir}
         Output format   : ${params.output_format}
         Work directory  : ${workflow.workDir}
         -----------------------------------------
         """

// Sanity check for the query file
if ( !params.query_file ) {
    exit 1, "[Nextflow Pipeline Error] Query file not specified. Please use --query_file <file_path>."
}
if ( !file(params.query_file).exists() ) {
    exit 1, "[Nextflow Pipeline Error] Query file not found: ${params.query_file}"
}

// Define the BLAST process
process run_blast {
    tag "BLASTing ${params.blast_program} against ${params.db_name}"
    publishDir params.outdir, mode: 'copy', overwrite: true // Copies output to the specified outdir

    input:
    path query_fasta_file   // The query FASTA file
    val database            // The name of the BLAST database
    val program             // The BLAST program to use
    val format_code         // The output format code for BLAST

    output:
    path "blast_results.txt" // The expected output file name

    script:
    """
    echo "Starting ${program} with query ${query_fasta_file} against database ${database}..."
    ${program} -query ${query_fasta_file} -db ${database} -out blast_results.txt -outfmt ${format_code}
    echo "${program} completed."
    """
}

// Define the main workflow
workflow {
    query_input_ch = Channel.fromPath(params.query_file)
    run_blast(query_input_ch, params.db_name, params.blast_program, params.output_format)
}